#!/usr/bin/env python3
"""A cluster without `app_repos` renders exactly as it did before tenants existed.

fleet-ops `standalone-app-repos` (jgct#214) adds tenants to this template: a
schema field, plugin derivations, a loop in `ks.yaml.j2`, a new
`kubernetes/tenants/` tree. Every cluster in the fleet today has no tenants, and
every one of them would be re-rendered by the next `task configure`. So the
first thing that has to hold -- before any tenant object is right -- is that the
tenant code is invisible to a cluster that does not use it.

That is asserted two ways, because the useful one cannot run in CI:

1. **Always (CI):** for each fixture, the render with `app_repos` absent is
   byte-identical to the render with `app_repos: []`, and neither contains a
   tenant object (a `kubernetes/tenants/` path, a Kustomization named
   `cluster-tenants` or `tenant-*`, or a `jg.tenant` label). This survives
   every future PR, because it compares the template with itself.

2. **On demand (`--against <ref>`):** each fixture rendered with the template
   at `<ref>` and with this tree, compared byte for byte. That is the real
   "nothing changed for existing clusters" reading, and every jgct#214 PR
   pastes it. It is NOT in CI: an unrelated template change is *supposed* to
   change the render, and a guard that fires on correct input gets switched off.

The fixtures are four complete, `cue vet`-valid inputs chosen to walk different
branches (profile, provisioning path, storage, extras, claude instances, auth0,
repository visibility). A fixture that fails `cue vet` is a defect in this
guard, not in the template -- it would be testing a cluster nobody can render
(`~/.claude/CLAUDE.md`: a fixture can invent a value a cluster cannot produce).
Addresses are RFC 5737 documentation ranges: this repo is public.

Each render runs the real makejinja on a private copy of the template inputs,
with placeholder credential files and a throwaway age key generated per run.
Nothing is written outside a temporary directory.

Exit 0 pass, 1 fail, 2 could not measure (a tool is missing). A failure wins
over "could not measure": a red result found before a tool went missing is
still red.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent

# What a render reads from the repo. Everything else (scripts/, .github/, docs)
# cannot affect the output, so it is not copied.
TEMPLATE_INPUTS = ["templates", "makejinja.toml", "trello-notifier.sample.yaml"]
SCHEMA = ".taskfiles/template/resources/cluster.schema.cue"

_COMMON = dict(
    storage_backend="nfs",
    node_cidr="192.0.2.0/24",
    cluster_svc_cidr="10.96.0.0/12",
    cloudflare_domain="example.com",
    cloudflare_token="placeholder-not-a-real-token",
    repository_name="example/rendertest",
    cluster_name="rendertest",
)

# An appliance is local-path only and must declare its off-site backup and
# that its age key is escrowed (schema, `deployment_profile == "appliance"`).
_APPLIANCE = dict(
    deployment_profile="appliance",
    provisioning_path="omni",
    storage_backend="local-path",
    age_key_escrowed=True,
    backup_r2_bucket="placeholder",
    backup_r2_endpoint="https://example.invalid",
    backup_r2_access_key_id="placeholder",
    backup_r2_secret_access_key="placeholder",
)

_TALOS_NODES = [
    dict(name=f"node-{i}", address=f"192.0.2.{10 + i}", controller=True,
         disk="/dev/sda", mac_addr=f"02:00:00:00:00:0{i}",
         schematic_id="0" * 64)
    for i in (1, 2, 3)
]

# (name, cluster.yaml, nodes)
FIXTURES: list[tuple[str, dict, list]] = [
    ("appliance-minimal", dict(
        _COMMON, **_APPLIANCE,
        claudecode_auth0=False,
        ttyd_credential="ops:placeholder-not-a-real-credential",
    ), []),
    ("appliance-instances-auth0", dict(
        _COMMON, **_APPLIANCE,
        claude_instances=["cc"],
        claudecode_auth0_domain="example.invalid",
        claudecode_auth0_client_id="placeholder",
        claudecode_auth0_client_secret="placeholder",
        claudecode_allowed_emails="ops@example.invalid",
        extras=["default/postgres"],
    ), []),
    ("full-talos-private", dict(
        _COMMON,
        deployment_profile="full",
        provisioning_path="talos",
        storage_backend="replicated",
        repository_visibility="private",
        accept_node_pinning=True,
        cluster_api_addr="192.0.2.100",
        cluster_gateway_addr="192.0.2.101",
        cluster_dns_gateway_addr="192.0.2.102",
        cloudflare_gateway_addr="192.0.2.103",
        claudecode_auth0=False,
        ttyd_credential="ops:placeholder-not-a-real-credential",
        extras=["default/postgres", "default/mqtt"],
    ), _TALOS_NODES),
    ("full-omni-extras", dict(
        _COMMON,
        deployment_profile="full",
        provisioning_path="omni",
        cluster_api_addr="192.0.2.100",
        cluster_gateway_addr="192.0.2.101",
        cluster_dns_gateway_addr="192.0.2.102",
        cloudflare_gateway_addr="192.0.2.103",
        nas_server="192.0.2.50",
        nas_path="/volume1/placeholder",
        accept_node_pinning=True,
        claudecode_auth0=False,
        ttyd_credential="ops:placeholder-not-a-real-credential",
        extras=["default/postgres", "default/mariadb", "freepbx/freepbx"],
    ), []),
]

_PLACEHOLDERS = {
    "cloudflare-tunnel.json": json.dumps({
        "AccountTag": "placeholder", "TunnelSecret": "cGxhY2Vob2xkZXI=",
        "TunnelID": "00000000-0000-0000-0000-000000000000"}),
    "github-deploy.key": "placeholder-not-a-key\n",
    "github-push-token.txt": "placeholder-not-a-token\n",
    "auth0.json": json.dumps({
        "domain": "example.invalid", "client_id": "placeholder",
        "client_secret": "placeholder", "allowed_emails": ["ops@example.invalid"]}),
}


class CannotMeasure(Exception):
    pass


def tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise CannotMeasure(f"`{name}` not on PATH (run under `mise exec --`)")
    return path


def dump_yaml(obj) -> str:
    # JSON is YAML; it keeps this guard free of a yaml dependency for writing.
    return json.dumps(obj, indent=2) + "\n"


def stage(tree: Path, work: Path, fixture: dict, nodes: list, age_key: Path) -> None:
    for name in TEMPLATE_INPUTS:
        src = tree / name
        if src.is_dir():
            shutil.copytree(src, work / name, symlinks=True)
        else:
            shutil.copy2(src, work / name)
    shutil.copy2(work / "trello-notifier.sample.yaml", work / "trello-notifier.yaml")
    (work / "cluster.yaml").write_text(dump_yaml(fixture))
    (work / "nodes.yaml").write_text(dump_yaml({"nodes": nodes}))
    shutil.copy2(age_key, work / "age.key")
    for name, body in _PLACEHOLDERS.items():
        (work / name).write_text(body)


def render(tree: Path, fixture: dict, nodes: list, age_key: Path) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory(prefix="tenant-render.") as tmp:
        work = Path(tmp)
        stage(tree, work, fixture, nodes, age_key)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([tool("makejinja"), "--output", "./out/"],
                              cwd=work, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = "\n".join(proc.stderr.strip().splitlines()[-3:])
            raise RuntimeError(f"makejinja exited {proc.returncode}:\n{tail}")
        out = work / "out"
        files = {str(p.relative_to(out)): p.read_bytes()
                 for p in sorted(out.rglob("*")) if p.is_file()}
        if not files:
            raise RuntimeError("makejinja exited 0 but rendered no files")
        return files


def vet(tree: Path, fixture: dict, nodes: list) -> str | None:
    """Return None if the fixture is valid, else cue's first lines."""
    merged = dict(fixture, nodes=nodes)
    with tempfile.TemporaryDirectory(prefix="tenant-vet.") as tmp:
        cfg = Path(tmp) / "merged.yaml"
        cfg.write_text(dump_yaml(merged))
        proc = subprocess.run([tool("cue"), "vet", str(cfg), str(tree / SCHEMA)],
                              capture_output=True, text=True)
    if proc.returncode == 0:
        return None
    return "\n".join(proc.stderr.strip().splitlines()[:4])


def tenant_traces(files: dict[str, bytes]) -> list[str]:
    found = []
    for path, body in files.items():
        if path.startswith("kubernetes/tenants/") or "/tenants/" in path:
            found.append(f"{path}: a tenants/ path")
            continue
        text = body.decode("utf-8", "replace")
        for needle in ("name: cluster-tenants", "name: tenant-", "jg.tenant"):
            if needle in text:
                found.append(f"{path}: contains `{needle}`")
    return found


def diff_names(a: dict[str, bytes], b: dict[str, bytes]) -> list[str]:
    out = [f"only in first: {p}" for p in sorted(a.keys() - b.keys())]
    out += [f"only in second: {p}" for p in sorted(b.keys() - a.keys())]
    out += [f"differs: {p}" for p in sorted(a.keys() & b.keys()) if a[p] != b[p]]
    return out


def checkout(ref: str, dest: Path) -> None:
    git = tool("git")
    archive = subprocess.run([git, "-C", str(ROOT), "archive", ref, "--", *TEMPLATE_INPUTS],
                             capture_output=True)
    if archive.returncode != 0:
        raise CannotMeasure(f"git archive {ref}: {archive.stderr.decode().strip()}")
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tree", type=Path, default=ROOT,
                    help="template tree to check (default: this repo)")
    ap.add_argument("--against", metavar="REF",
                    help="also compare each fixture's render with the template at REF")
    args = ap.parse_args()

    failures: list[str] = []
    try:
        for name, fixture, nodes in FIXTURES:
            problem = vet(args.tree, fixture, nodes)
            if problem:
                failures.append(f"[{name}] fixture fails cue vet (guard defect):\n{problem}")
        if failures:
            raise RuntimeError("fixtures invalid")

        with tempfile.TemporaryDirectory(prefix="tenant-key.") as tmp:
            key = Path(tmp) / "age.key"
            proc = subprocess.run([tool("age-keygen"), "-o", str(key)],
                                  capture_output=True, text=True)
            if proc.returncode != 0 or not key.is_file():
                raise CannotMeasure(f"age-keygen failed: {proc.stderr.strip()}")

            ref_tree = None
            if args.against:
                ref_tree = Path(tmp) / "ref"
                ref_tree.mkdir()
                checkout(args.against, ref_tree)

            for name, fixture, nodes in FIXTURES:
                try:
                    absent = render(args.tree, fixture, nodes, key)
                    empty = render(args.tree, dict(copy.deepcopy(fixture), app_repos=[]),
                                   nodes, key)
                    before = (render(ref_tree, fixture, nodes, key)
                              if ref_tree is not None else None)
                except RuntimeError as e:
                    failures.append(f"[{name}] render failed: {e}")
                    continue
                diffs = diff_names(absent, empty)
                if diffs:
                    failures.append(f"[{name}] `app_repos` absent vs `[]` differ:\n  "
                                    + "\n  ".join(diffs))
                for label, files in (("absent", absent), ("[]", empty)):
                    traces = tenant_traces(files)
                    if traces:
                        failures.append(f"[{name}] tenant objects with `app_repos` {label}:\n  "
                                        + "\n  ".join(traces))
                line = f"[{name}] {len(absent)} files rendered; absent == []"
                if before is not None:
                    diffs = diff_names(before, absent)
                    if diffs:
                        failures.append(f"[{name}] render differs from {args.against}:\n  "
                                        + "\n  ".join(diffs))
                    else:
                        line += f"; identical to {args.against} ({len(before)} files)"
                if not any(f.startswith(f"[{name}]") for f in failures):
                    print("ok  " + line)
    except CannotMeasure as e:
        if failures:
            print("\n".join("FAIL " + f for f in failures))
            print(f"(also could not finish: {e})")
            return 1
        print(f"COULD NOT MEASURE: {e}")
        return 2
    except RuntimeError as e:
        if str(e) != "fixtures invalid":
            raise

    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print(f"PASS -- {len(FIXTURES)} fixtures: no tenant object and no byte change "
          f"when `app_repos` is absent or empty"
          + (f"; each render identical to {args.against}" if args.against else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

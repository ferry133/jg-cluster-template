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

3. **Always (CI), from task 3.3:** one fixture rendered WITH two tenants
   (a vendor and a multi-namespace agent), and the Flux objects in `ks.yaml`
   asserted field by field: one `cluster-tenants`; per tenant a ServiceAccount,
   a GitRepository on its own deploy key, and a Kustomization that runs as
   `tenant-<name>`, decrypts with `tenant-<name>-sops-age` and has **no**
   `postBuild` (cluster-secrets is every credential the cluster has). Every
   other document in `ks.yaml` and every other file must equal the tenant-free
   render, so adding a tenant cannot change anything that is not the tenant.
   No ClusterRoleBinding anywhere may name a tenant ServiceAccount. Without
   this part, "identical when absent" would also be what a tenant loop that
   never renders looks like.

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


# Part 3. Built on full-omni-extras: a narrowed shared pool (three declared
# gateway addresses) so a lan_ip grant is legal, and `full` so it is not
# refused as an appliance.
TENANT_BASE = "full-omni-extras"
TENANTS = [
    dict(name="acme", repository="fixture/acme-app", kind="vendor"),
    dict(name="shop", repository="fixture/shop-app", kind="agent",
         namespaces=["shop", "shop-db"], branch="prod",
         grants=dict(baseline=True, lan_ip=1),
         lan_ip_range=dict(start="192.0.2.200", stop="192.0.2.200")),
]
KS = "kubernetes/flux/cluster/ks.yaml"


def docs(body: bytes) -> list[dict]:
    """Every YAML document as a dict, via yq (CI's python has no PyYAML)."""
    proc = subprocess.run([tool("yq"), "-o=json", "-I=0", "."], input=body,
                          capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"yq could not parse: {proc.stderr.decode().strip()}")
    out = [json.loads(l) for l in proc.stdout.decode().splitlines() if l.strip()]
    return [d for d in out if isinstance(d, dict)]


def ident(d: dict) -> tuple[str, str]:
    return d.get("kind", ""), d.get("metadata", {}).get("name", "")


def tenant_shape(with_t: dict[str, bytes], without: dict[str, bytes]) -> list[str]:
    bad: list[str] = []
    if KS not in with_t:
        return [f"{KS} not rendered"]
    # Nothing but ks.yaml (and, from task 3.4, kubernetes/tenants/) may differ.
    for d in diff_names(without, with_t):
        path = d.split(": ", 1)[1]
        if path != KS and not path.startswith("kubernetes/tenants/"):
            bad.append(f"adding tenants changed a non-tenant file: {d}")
    got = docs(with_t[KS])
    base = docs(without[KS])
    tenant_names = {f"tenant-{t['name']}" for t in TENANTS} | {"cluster-tenants"}
    rest = [d for d in got if ident(d)[1] not in tenant_names]
    if rest != base:
        bad.append(f"{KS}: the non-tenant documents differ from the tenant-free render "
                   f"({len(rest)} vs {len(base)} documents)")
    by = {}
    for d in got:
        by.setdefault(ident(d), []).append(d)

    def one(kind, name):
        found = by.get((kind, name), [])
        if len(found) != 1:
            bad.append(f"{kind}/{name}: {len(found)} rendered, expected 1")
            return {}
        if found[0].get("metadata", {}).get("namespace") != "flux-system":
            bad.append(f"{kind}/{name}: not in flux-system")
        return found[0]

    def want(obj, path, expected, label):
        cur = obj
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if cur != expected:
            bad.append(f"{label} .{'.'.join(path)} = {cur!r}, expected {expected!r}")

    ct = one("Kustomization", "cluster-tenants")
    if ct:
        lbl = "Kustomization/cluster-tenants"
        want(ct, ["spec", "path"], "./kubernetes/tenants", lbl)
        want(ct, ["spec", "prune"], True, lbl)
        want(ct, ["spec", "sourceRef", "name"], "flux-system", lbl)
        want(ct, ["spec", "dependsOn"], [{"name": "cluster-apps-base"}], lbl)
        # The cluster key decrypts the platform's own tenant Secrets.
        want(ct, ["spec", "decryption"], {"provider": "sops"}, lbl)
    for t in TENANTS:
        n = f"tenant-{t['name']}"
        one("ServiceAccount", n)
        g = one("GitRepository", n)
        if g:
            lbl = f"GitRepository/{n}"
            want(g, ["spec", "url"], f"ssh://git@github.com/{t['repository']}.git", lbl)
            want(g, ["spec", "ref"], {"branch": t.get("branch", "main")}, lbl)
            want(g, ["spec", "secretRef", "name"], f"{n}-git-auth", lbl)
        k = one("Kustomization", n)
        if k:
            lbl = f"Kustomization/{n}"
            want(k, ["spec", "serviceAccountName"], n, lbl)
            want(k, ["spec", "decryption"],
                 {"provider": "sops", "secretRef": {"name": f"{n}-sops-age"}}, lbl)
            want(k, ["spec", "sourceRef"],
                 {"kind": "GitRepository", "name": n, "namespace": "flux-system"}, lbl)
            want(k, ["spec", "prune"], True, lbl)
            want(k, ["spec", "dependsOn"], [{"name": "cluster-tenants"}], lbl)
            for forbidden in ("postBuild", "targetNamespace", "kubeConfig"):
                if forbidden in k.get("spec", {}):
                    bad.append(f"{lbl} has spec.{forbidden}")
    # No ClusterRoleBinding, in any rendered file, may name a tenant SA.
    for path, body in with_t.items():
        if not path.endswith((".yaml", ".yml")):
            continue
        for d in docs(body):
            if d.get("kind") == "ClusterRoleBinding":
                for s in d.get("subjects") or []:
                    if str(s.get("name", "")).startswith("tenant-"):
                        bad.append(f"{path}: ClusterRoleBinding/{ident(d)[1]} names {s.get('name')}")
    return bad


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

            # Part 3: the shape of a render that HAS tenants.
            for name, fixture, nodes in FIXTURES:
                if name != TENANT_BASE:
                    continue
                with_t = dict(copy.deepcopy(fixture), app_repos=copy.deepcopy(TENANTS))
                problem = vet(args.tree, with_t, nodes)
                if problem:
                    failures.append(f"[with-tenants] fixture fails cue vet (guard defect):\n{problem}")
                    break
                try:
                    got = render(args.tree, with_t, nodes, key)
                    without = render(args.tree, fixture, nodes, key)
                except RuntimeError as e:
                    failures.append(f"[with-tenants] render failed: {e}")
                    break
                bad = tenant_shape(got, without)
                if bad:
                    failures.append("[with-tenants] " + "\n  ".join(bad))
                else:
                    print(f"ok  [with-tenants] {len(TENANTS)} tenants on {TENANT_BASE}: "
                          f"cluster-tenants + SA/GitRepository/Kustomization each, "
                          f"no postBuild, no tenant ClusterRoleBinding, nothing else changed")
                break
            else:
                failures.append(f"[with-tenants] base fixture {TENANT_BASE} not found (guard defect)")
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
          f"when `app_repos` is absent or empty; with tenants, only tenant objects"
          + (f"; each render identical to {args.against}" if args.against else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

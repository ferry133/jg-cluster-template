#!/usr/bin/env python3
"""nfs_provisioner: false suspends nfs-subdir on an NFS cluster and moves nothing else; absent or true renders as before.

jgct#277 (ferry133 2026-11-26, option A). On real makejinja renders of the
fixtures check-tenant-render.py maintains:

1. **Not set, no change**: every fixture, and the NFS fixture with an
   explicit `nfs_provisioner: true`, renders the same as the fixture without
   the field. With `--against <ref>` each plain fixture is byte-identical to
   the template at <ref>. On the NFS fixture nfs-client-provisioner is NOT
   suspended (control: the case below has something to change).
2. **false on NFS** (every class the template places named local-path, then
   all named longhorn as on jg-jiahd):
   ks.yaml gains exactly one suspend patch, for nfs-client-provisioner; ks.yaml
   is the only file that differs; cluster-secrets is byte-identical, so
   DEFAULT_STORAGE_CLASS, LOCAL_PATH_IS_DEFAULT, LONGHORN_IS_DEFAULT and
   NAS_IS_DEFAULT keep their values (the acceptance cell on #277: longhorn
   stays the one default where it was).
3. **Refusals**, each for its own reason: the field on a non-NFS backend;
   false while db_storage_class, the claude-code workspace class or the config
   class resolves to sc-nas. cue vet refuses a value that is not a boolean.

What this does NOT check: that a cluster's live objects go away. Suspending
stops reconciliation; the installed HelmRelease and StorageClass stay until
deleted by hand (cluster.sample.yaml says so).

Exit 0 pass, 1 fail, 2 could not measure. A failure wins.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tr = _load("tr", "check-tenant-render.py")

CS = tr.CS
KS = tr.KS
TARGET = "nfs-client-provisioner"
NFS = "full-omni-extras"
NON_NFS = "appliance-minimal"
FLAGS = ("DEFAULT_STORAGE_CLASS", "LOCAL_PATH_IS_DEFAULT", "LONGHORN_IS_DEFAULT", "NAS_IS_DEFAULT")


def fixture(name: str) -> tuple[dict, list]:
    hit = next(((f, nodes) for n, f, nodes in tr.FIXTURES if n == name), None)
    if hit is None:
        raise tr.CannotMeasure(f"fixture {name!r} is gone from check-tenant-render.py")
    return dict(hit[0]), hit[1]


def cs_data(files: dict[str, bytes]) -> dict:
    for d in tr.docs(files[CS]):
        if tr.ident(d) == ("Secret", "cluster-secrets"):
            return d.get("stringData") or {}
    return {}


def suspended(files: dict[str, bytes]) -> list[str]:
    """Names of Kustomizations the root sync patches to suspend: true."""
    out = []
    for d in tr.docs(files[KS]):
        for p in (d.get("spec") or {}).get("patches") or []:
            body = tr.yq_value(p.get("patch", "")) if isinstance(p.get("patch"), str) else None
            if isinstance(body, dict) and (body.get("spec") or {}).get("suspend") is True:
                out.append((p.get("target") or {}).get("name"))
    return out


def _only(field: str) -> dict:
    """provisioner off, every placed class on local-path except `field` on sc-nas."""
    f = dict(nfs_provisioner=False, db_storage_class="local-path",
             claudecode_workspace_storage_class="local-path",
             claudecode_config_storage_class="local-path")
    f[field] = "sc-nas"
    return f


REFUSALS = [
    # (name, fixture name, extra fields, reason substring). Each sc-nas case
    # puts exactly one field on sc-nas, so the message must name that field
    # alone: "<field> resolves" fails if the plugin lists the wrong one.
    ("set-on-non-nfs", NON_NFS, dict(nfs_provisioner=False), "nfs-subdir runs only on an NFS cluster"),
    ("true-on-non-nfs", NON_NFS, dict(nfs_provisioner=True), "nfs-subdir runs only on an NFS cluster"),
    ("db-on-nas", NFS, _only("db_storage_class"), "false, but db_storage_class resolves to sc-nas"),
    ("workspace-on-nas", NFS, _only("claudecode_workspace_storage_class"),
     "false, but claudecode_workspace_storage_class resolves to sc-nas"),
    ("config-on-nas", NFS, _only("claudecode_config_storage_class"),
     "false, but claudecode_config_storage_class resolves to sc-nas"),
    # Left to the defaults the workspace follows DEFAULT_STORAGE_CLASS, sc-nas.
    ("defaults-on-nas", NFS, dict(nfs_provisioner=False), "claudecode_workspace_storage_class"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tree", type=Path, default=ROOT)
    ap.add_argument("--against", metavar="REF")
    args = ap.parse_args()
    failures: list[str] = []
    passed = 0
    refusals = 0
    try:
        nfs, nfs_nodes = fixture(NFS)
        if nfs.get("storage_backend") != "nfs":
            raise tr.CannotMeasure(f"fixture {NFS!r} is no longer an NFS cluster")
        with tempfile.TemporaryDirectory(prefix="nfs-provisioner-render.") as tmp:
            key = Path(tmp) / "age.key"
            subprocess.run([tr.tool("age-keygen"), "-o", str(key)], capture_output=True, check=True)
            ref_tree = None
            if args.against:
                ref_tree = Path(tmp) / "ref"
                ref_tree.mkdir()
                tr.checkout(args.against, ref_tree)

            def render(f, nodes):
                return tr.render(args.tree, f, nodes, key)

            # 1. not set
            for name, fx, nodes in tr.FIXTURES:
                try:
                    files = render(fx, nodes)
                    before = tr.render(ref_tree, fx, nodes, key) if ref_tree else None
                except RuntimeError as e:
                    failures.append(f"[{name}] render failed: {e}")
                    continue
                bad = []
                if before is not None:
                    bad += [f"[{name}] differs from {args.against}: {d}" for d in tr.diff_names(before, files)]
                if name == NFS and TARGET in suspended(files):
                    bad.append(f"[{name}] {TARGET} is suspended with the field absent")
                failures += bad
                if not bad:
                    passed += 1
                    print(f"ok  [{name}] field absent"
                          + (f"; byte-identical to {args.against}" if before is not None else "")
                          + (f"; {TARGET} not suspended" if name == NFS else ""))
            plain = render(nfs, nfs_nodes)
            explicit = render(dict(nfs, nfs_provisioner=True), nfs_nodes)
            diff = tr.diff_names(plain, explicit)
            if diff:
                failures.append(f"[explicit-true] differs from the field absent: {diff}")
            else:
                passed += 1
                print("ok  [explicit-true] same render as the field absent")

            # 2. false on NFS, with both block tiers the default can follow
            for db in ("local-path", "longhorn"):
                label = f"off-db-{db}"
                # A NAS-less cluster names a block class for everything the
                # template places (jg-jiahd: all three longhorn); left to their
                # defaults, the workspace follows DEFAULT_STORAGE_CLASS (sc-nas)
                # and the render is refused -- case workspace-on-nas.
                base = dict(nfs, db_storage_class=db, claudecode_workspace_storage_class=db,
                            claudecode_config_storage_class=db)
                if db == "longhorn":
                    base["replicated_storage"] = True
                on = render(base, nfs_nodes)
                off = render(dict(base, nfs_provisioner=False), nfs_nodes)
                bad = []
                added = [n for n in suspended(off) if n not in suspended(on)]
                removed = [n for n in suspended(on) if n not in suspended(off)]
                if added != [TARGET] or removed:
                    bad.append(f"[{label}] suspend patches added {added}, removed {removed}; expected added [{TARGET!r}]")
                stray = [d for d in tr.diff_names(on, off) if d != f"differs: {KS}"]
                if stray:
                    bad.append(f"[{label}] the field changed more than ks.yaml: {stray}")
                a, b = cs_data(on), cs_data(off)
                moved = [k for k in FLAGS if a.get(k) != b.get(k)]
                if moved:
                    bad.append(f"[{label}] storage keys moved: {moved}")
                want_lh = "true" if db == "longhorn" else "false"
                if b.get("LONGHORN_IS_DEFAULT") != want_lh:
                    bad.append(f"[{label}] LONGHORN_IS_DEFAULT is {b.get('LONGHORN_IS_DEFAULT')!r}, expected {want_lh!r}")
                failures += bad
                if not bad:
                    passed += 1
                    print(f"ok  [{label}] one suspend patch added, for {TARGET}; only ks.yaml differs; "
                          f"{', '.join(f'{k}={b.get(k)}' for k in FLAGS)} unchanged")

            # 3. refusals
            for name, fx_name, extra, reason in REFUSALS:
                fx, nodes = fixture(fx_name)
                try:
                    render(dict(fx, **extra), nodes)
                except RuntimeError as e:
                    msg = str(e)
                    if reason not in msg:
                        failures.append(f"[{name}] refused, but not for its own reason (no {reason!r}): {msg[-200:]}")
                    else:
                        refusals += 1
                        print(f"ok  [{name}] refused: {reason!r}")
                    continue
                failures.append(f"[{name}] rendered; it must be refused ({reason!r})")
            for name, fx, accept in (
                ("vet-false", dict(nfs, nfs_provisioner=False), True),
                ("vet-not-bool", dict(nfs, nfs_provisioner="no"), False),
            ):
                problem = tr.vet(args.tree, fx, nfs_nodes)
                if (problem is None) != accept:
                    failures.append(f"[{name}] cue vet {'refused' if problem else 'accepted'} it"
                                    + (f": {problem}" if problem else ""))
                else:
                    refusals += 1
                    print(f"ok  [{name}] cue vet {'accepts' if accept else 'refuses'}")
    except tr.CannotMeasure as e:
        if failures:
            print("\n".join("FAIL " + f for f in failures))
            return 1
        print(f"COULD NOT MEASURE: {e}")
        return 2
    except RuntimeError as e:
        failures.append(f"a good scenario failed to render (guard or template defect): {e}")
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print(f"PASS -- {passed} render cases and {refusals} refusal/vet cases"
          + (f", the plain fixtures byte-identical to {args.against}" if args.against else "")
          + ". Not checked here: that live objects go away (suspend does not uninstall).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

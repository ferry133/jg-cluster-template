#!/usr/bin/env python3
"""Every render has exactly one default StorageClass, it is the block tier, and on an NFS cluster sc-nas exists but is not the default.

jgct#257 (ferry133 2026-11-01): app state belongs on the block tier, so a PVC
that names no class must not land on the NAS. Before #257, nfs-subdir claimed
the default whenever it ran, so "did not choose" meant "put it on the NAS".

Which class is the default is decided by three helm values in jg-base. Each
reads a cluster-secrets key and falls back when the key is absent:

    local-path  defaultClass: ${LOCAL_PATH_IS_DEFAULT:=false}
    sc-nas      defaultClass: ${NAS_IS_DEFAULT:=true}       (jg-base#242)
    longhorn    defaultClass: ${LONGHORN_IS_DEFAULT:=false} (jg-base#242)

So the verdict is computed from the rendered cluster-secrets plus those
fallbacks. ⚠️ The fallbacks are copied here as constants. This repo cannot
read jg-base, and a fallback that changes there is invisible here. It is the
one premise this guard does not measure.

Checked, on real makejinja renders of check-tenant-render.py's fixtures:

1. Every fixture: exactly 1 default class, and it is not sc-nas. On the NFS
   fixture sc-nas still exists (NAS_SERVER rendered), and the default is
   local-path.
2. The NFS fixture with db_storage_class longhorn: the default is longhorn,
   not local-path. That is the block tier the cluster chose, and it does not
   pin.
3. Negative control, always run: the same judge applied to the NFS
   cluster-secrets the template rendered before #257 (LOCAL_PATH_IS_DEFAULT
   "false", no NAS_IS_DEFAULT) must be judged non-compliant, because sc-nas
   is the default. With `--against <ref>`, that control is a real render of
   <ref>. In addition, every non-NFS fixture must be byte-identical to <ref>
   (acceptance 3: local-path and replicated do not change). Not in CI, for
   check-tenant-render.py's reason.

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
_spec = importlib.util.spec_from_file_location("tr", ROOT / "scripts" / "check-tenant-render.py")
tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tr)

# jg-base's fallbacks (see the docstring). key -> (class, value when absent)
JG_BASE = {
    "LOCAL_PATH_IS_DEFAULT": ("local-path", "false"),
    "NAS_IS_DEFAULT": ("sc-nas", "true"),
    "LONGHORN_IS_DEFAULT": ("longhorn", "false"),
}
NFS_FIXTURE = "full-omni-extras"


def cs_data(files: dict[str, bytes]) -> dict:
    for d in tr.docs(files[tr.CS]):
        if tr.ident(d) == ("Secret", "cluster-secrets"):
            return d.get("stringData") or {}
    raise tr.CannotMeasure(f"no Secret cluster-secrets in {tr.CS}")


def defaults(cs: dict) -> tuple[bool, list[str]]:
    """(is NFS, the classes that claim the default)."""
    nfs = bool(cs.get("NAS_SERVER"))
    out = []
    for key, (cls, absent) in JG_BASE.items():
        if cls == "sc-nas" and not nfs:
            continue            # nfs-subdir does not run, so the class does not exist
        if str(cs.get(key, absent)).lower() == "true":
            out.append(cls)
    return nfs, out


def judge(label: str, cs: dict, want: str) -> list[str]:
    nfs, d = defaults(cs)
    bad = []
    if len(d) != 1:
        bad.append(f"[{label}] {len(d)} default classes {d}; exactly 1 is required")
    if "sc-nas" in d:
        bad.append(f"[{label}] sc-nas is a default; it must be used only where named (jgct#257)")
    if d != [want]:
        bad.append(f"[{label}] default {d}, expected [{want!r}]")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tree", type=Path, default=ROOT)
    ap.add_argument("--against", metavar="REF")
    args = ap.parse_args()
    failures: list[str] = []
    try:
        fixtures = {n: (f, nodes) for n, f, nodes in tr.FIXTURES}
        if NFS_FIXTURE not in fixtures:
            raise tr.CannotMeasure(f"fixture {NFS_FIXTURE!r} is gone from check-tenant-render.py")
        with tempfile.TemporaryDirectory(prefix="default-sc.") as tmp:
            key = Path(tmp) / "age.key"
            subprocess.run([tr.tool("age-keygen"), "-o", str(key)], capture_output=True, check=True)
            ref_tree = None
            if args.against:
                ref_tree = Path(tmp) / "ref"
                ref_tree.mkdir()
                tr.checkout(args.against, ref_tree)

            nfs_seen = 0
            for name, (fixture, nodes) in fixtures.items():
                files = tr.render(args.tree, fixture, nodes, key)
                cs = cs_data(files)
                nfs, _ = defaults(cs)
                nfs_seen += nfs
                bad = judge(name, cs, "local-path")
                if ref_tree is not None:
                    before = tr.render(ref_tree, fixture, nodes, key)
                    if nfs:
                        ref_bad = judge(f"{name}@{args.against}", cs_data(before), "local-path")
                        if not ref_bad:
                            bad.append(f"[{name}] negative control: {args.against}'s render "
                                       "was judged compliant; the judge cannot tell")
                        else:
                            print(f"ok  [{name}@{args.against}] judged non-compliant: {ref_bad[0]}")
                    else:
                        bad += [f"[{name}] differs from {args.against}: {x}"
                                for x in tr.diff_names(before, files)]
                failures += bad
                if not bad:
                    print(f"ok  [{name}] {'nfs' if nfs else 'non-nfs'}: one default, local-path"
                          + (", sc-nas present and not default" if nfs else "")
                          + (f"; byte-identical to {args.against}"
                             if ref_tree is not None and not nfs else ""))
            if nfs_seen != 1:
                raise tr.CannotMeasure(f"{nfs_seen} fixtures rendered NAS_SERVER; expected exactly "
                                       f"{NFS_FIXTURE} -- the NFS case was not exercised")

            # 2. NFS + longhorn block tier
            f, nodes = fixtures[NFS_FIXTURE]
            lh = dict(f, db_storage_class="longhorn", replicated_storage=True)
            bad = judge("nfs-db-longhorn", cs_data(tr.render(args.tree, lh, nodes, key)), "longhorn")
            failures += bad
            if not bad:
                print("ok  [nfs-db-longhorn] one default, longhorn (the block tier the cluster chose)")

            # 3. negative control, synthesized from the pre-#257 shape
            pre = dict(cs_data(tr.render(args.tree, f, nodes, key)))
            for k in ("NAS_IS_DEFAULT", "LONGHORN_IS_DEFAULT"):
                pre.pop(k, None)
            pre["LOCAL_PATH_IS_DEFAULT"] = "false"
            ctrl = judge("pre-257-shape", pre, "local-path")
            if not ctrl:
                failures.append("[pre-257-shape] negative control judged compliant; the judge cannot tell")
            else:
                print(f"ok  [pre-257-shape] negative control judged non-compliant: {ctrl[0]}")
    except tr.CannotMeasure as e:
        if failures:
            print("\n".join("FAIL " + x for x in failures))
            return 1
        print(f"COULD NOT MEASURE: {e}")
        return 2
    except RuntimeError as e:
        failures.append(f"a good scenario failed to render (guard or template defect): {e}")
    if failures:
        print("\n".join("FAIL " + x for x in failures))
        return 1
    print(f"PASS -- {len(tr.FIXTURES)} fixtures each have exactly one default, the block tier; "
          "NFS + longhorn defaults to longhorn; the pre-#257 shape is judged non-compliant"
          + (f"; non-NFS fixtures byte-identical to {args.against}" if args.against else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

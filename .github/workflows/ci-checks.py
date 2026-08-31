#!/usr/bin/env python3
"""Which of this repo's check scripts CI runs, and why the rest are not run.

Measured 2026-08-31 in a fresh checkout with no `cluster.yaml`, no `age.key`,
no rendered `kubernetes/` and no cluster: seven of the twelve `check-*` scripts
pass on their own, and five cannot see their subject from here. The five are
listed with the reason rather than dropped, because a list that silently stops
at the runnable ones reads exactly like a list that covers everything.

`--audit` fails if `scripts/check-*` contains anything not in either list. That
is the failure this file exists for: `#58` added a check script and nothing ran
it, which is how a repo with eleven guards ended up with no CI at all.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Exit 0 in a bare checkout. Measured, not assumed.
RUN = [
    "check-claude-instances-default.py",
    "check-encrypt-secrets.sh",
    "check-forwarded-header-trust.py",
    "check-lb-pool-render.py",
    "check-nas-backup.py",
    "check-node-dns-path.py",
    "check-template-integrity.py",
]

# Cannot see their subject from a bare template checkout. The reason is the
# point: "not run" with a reason is a third outcome, and dropping these from
# the report would make the run look complete.
SKIP = {
    "check-backup-recipient.py":
        "reads the rendered cluster-secrets; exits 2 CANNOT MEASURE here",
    "check-longhorn-backup.py":
        "reads rendered kubernetes/; exits 2 COULD NOT MEASURE here",
    "check-claudecode-auth.py":
        "needs a cluster.yaml, which the template repo does not have",
    "check-lb-pool-covers-live.py":
        "needs a live cluster (kubectl) and the age key to decrypt secrets",
    "check-template-drift.py":
        "compares two repos; needs a per-user repo to compare against",
}


def scripts_present() -> set[str]:
    return {p.name for p in (ROOT / "scripts").glob("check-*")}


def audit() -> int:
    present, known = scripts_present(), set(RUN) | set(SKIP)
    unclassified = sorted(present - known)
    missing = sorted(known - present)
    for name in unclassified:
        print(f"FAIL  scripts/{name} is in neither RUN nor SKIP")
        print("      A check script with no runner is how #59 happened. Add it")
        print("      to RUN, or to SKIP with the reason it cannot run here.")
    for name in missing:
        print(f"FAIL  {name} is listed here but not in scripts/")
        print("      A list naming a file that no longer exists still reads as")
        print("      coverage.")
    if unclassified or missing:
        return 1
    print(f"ok    {len(present)} check scripts, {len(RUN)} run here, "
          f"{len(SKIP)} cannot see their subject from a bare checkout")
    return 0


def run() -> int:
    failed = []
    for name in RUN:
        path = ROOT / "scripts" / name
        cmd = (["bash", str(path)] if path.suffix == ".sh"
               else ["python3", str(path)])
        print(f"\n──────── {name}", flush=True)
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        print(f"exit={rc}", flush=True)
        if rc != 0:
            failed.append((name, rc))

    print("\n" + "=" * 60)
    for name, reason in sorted(SKIP.items()):
        print(f"not run  {name} — {reason}")
    print("=" * 60)

    if failed:
        for name, rc in failed:
            print(f"::error::{name} exited {rc}")
        return 1
    print(f"ok — {len(RUN)} check scripts passed, {len(SKIP)} not run (above)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if not (args.audit or args.run):
        ap.error("pass --audit or --run")
    sys.exit((audit() if args.audit else 0) or (run() if args.run else 0))

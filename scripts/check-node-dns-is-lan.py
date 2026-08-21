#!/usr/bin/env python3
"""Assert what `node_dns_is_lan` derives to, per node_dns_servers shape.

daily-check probes `internal.<domain>` through the node's ordinary resolution
path and raises an alarm when it fails. This flag decides whether that probe
runs at all, so both ways of getting it wrong are silent:

  stuck true   a cluster whose nodes point at 1.1.1.1 alarms every morning
               while its LAN is perfectly healthy — Cloudflare will not serve
               the RFC1918 answer (deployment-profiles D29), so the probe can
               never pass there. A permanently red row trains the reader to
               ignore the channel that carries seventeen other checks.

  stuck false  the row disappears from every cluster at once, and a check that
               emits nothing reads exactly like a check that passed.

Neither shows up in a rendered manifest, because the flag is computed before
rendering and only ever appears as one word.

It exercises the real Plugin.data() rather than a copy of its logic. A
reimplementation here would drift, and the copy that drifts is the one that
keeps passing.

Exit 0 if every case matches, 1 otherwise.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_plugin():
    """Import templates/scripts/plugin.py without a real makejinja."""
    mj = types.ModuleType("makejinja")
    pl = types.ModuleType("makejinja.plugin")

    class _Base:
        def __init__(self, *a, **k):
            pass

    pl.Plugin, pl.Data, pl.Filters, pl.Functions = _Base, dict, list, list
    mj.plugin = pl
    sys.modules.setdefault("makejinja", mj)
    sys.modules.setdefault("makejinja.plugin", pl)
    spec = importlib.util.spec_from_file_location(
        "_plugin", ROOT / "templates" / "scripts" / "plugin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE = dict(
    cluster_name="rendertest",
    node_cidr="10.9.1.0/24",
    cluster_svc_cidr="10.96.0.0/12",
    bootstrap_distro="talos",
    deployment_profile="full",
    claudecode_auth0=False,
    ttyd_credential="ops:placeholder-not-a-real-credential",
)

CASES = [
    # (name, extra cluster.yaml fields, expected node_dns_is_lan)
    (
        "unset — nodes take DNS from DHCP, so a node stands in for a LAN client",
        dict(),
        True,
    ),
    (
        "the applied default (1.1.1.1) is NOT the LAN, even though plugin.py sets it",
        dict(node_dns_servers=["1.1.1.1", "1.0.0.1"]),
        False,
    ),
    (
        "router as resolver",
        dict(node_dns_servers=["10.9.1.1"]),
        True,
    ),
    (
        "the cluster's own k8s-gateway",
        dict(node_dns_servers=["10.9.1.254"]),
        True,
    ),
    (
        "192.168/16 and 172.16/12 are LAN too",
        dict(node_dns_servers=["192.168.1.1", "172.20.0.1"]),
        True,
    ),
    (
        "one public entry is enough to make the probe meaningless",
        dict(node_dns_servers=["10.9.1.1", "8.8.8.8"]),
        False,
    ),
]


def main() -> int:
    plugin = load_plugin()
    failed = 0
    for name, extra, expected in CASES:
        data = dict(BASE, **extra)
        try:
            plugin.Plugin(data).data()
            got = data["node_dns_is_lan"]
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {name}\n        render raised {type(e).__name__}: {e}")
            failed += 1
            continue
        if got is expected:
            print(f"PASS  {name}\n        node_dns_is_lan = {got}")
        else:
            print(f"FAIL  {name}\n        expected {expected}, got {got!r}")
            failed += 1

    # Both stuck values pass a same-answer suite, so require the two answers to
    # actually differ across the cases above.
    answers = set()
    for _, extra, _ in CASES:
        d = dict(BASE, **extra)
        plugin.Plugin(d).data()
        answers.add(d["node_dns_is_lan"])
    if len(answers) < 2:
        print("\nFAIL  the derivation returned the same answer for every case —")
        print("      a flag that never varies is not being computed from anything.")
        failed += 1

    print()
    if failed:
        print(f"{failed} case(s) failed.")
        print("Stuck true alarms daily on a healthy LAN; stuck false removes the")
        print("row from every cluster, and an absent row reads like a passing one.")
        return 1
    print(f"ok — {len(CASES)} cases match, and the derivation varies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

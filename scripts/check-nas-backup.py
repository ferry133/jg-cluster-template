#!/usr/bin/env python3
"""Assert the two halves of the NAS backup decision: whether, and where.

They live in one file on purpose. `nas_backup` says whether a backup CronJob
renders at all; `nas_backup_path` says which export it writes to. Both are
statements about the same machine, and ferry133/jg-base#82 is what splitting
them across places costs: jg-base templated `server: ${NAS_SERVER}` per
cluster and hardwired `path: /volume2/backup1` beside it. Correct on jcom's
NAS, `mount.nfs: access denied` on jg-jiahd's, whose exports are all under
/volume3 -- and the CronJob object stayed healthy while not one dump had ever
been written. A guard that checked only the `whether` half would have been
green throughout.

This one word decides whether the database extras render their NAS backup
CronJob at all (jg-base selects a directory with it:
`.../postgres/backup/${NAS_BACKUP:=nfs}`), and both ways of getting it wrong
are quiet:

  stuck 'nfs'   an appliance renders a PersistentVolume with an empty
                `nfs.server`, the API server rejects it, and the Kustomization
                carrying it goes Ready=False. That is ferry133/jg-base#17,
                where the invalid PV lived alongside the database and took the
                database with it.

  stuck 'none'  every cluster with a NAS silently stops taking database dumps
                to it. Nothing goes red; the backups just stop, and that is
                indistinguishable from working until someone needs a restore.

The word also has to survive the trip into a `stringData` field. `''` is YAML
null and `false` is a YAML boolean, and either one gets the whole Secret
rejected -- ferry133/jg-base#16 cost a cluster its entire daily-check that way.

It exercises the real Plugin.data() rather than a copy of its logic. A
reimplementation here would drift, and the copy that drifts is the one that
keeps passing.

Exit 0 if every case matches, 1 otherwise.
"""

from __future__ import annotations

import importlib.util
import re
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

# Values a YAML 1.1 parser reads as something other than a string. The word
# lands in stringData on the way to the cluster, and kustomize does not keep
# the quotes around the placeholder it is substituted into.
NOT_A_STRING = {
    "", "~", "null", "Null", "NULL",
    "true", "True", "TRUE", "false", "False", "FALSE",
    "yes", "Yes", "YES", "no", "No", "NO",
    "on", "On", "ON", "off", "Off", "OFF",
}

CASES = [
    # (name, extra cluster.yaml fields, expected nas_backup)
    (
        "appliance — no NAS, so no NAS backup share to write to",
        dict(deployment_profile="appliance", storage_backend="local-path"),
        "none",
    ),
    (
        "nas_server unset on any profile is the same answer",
        dict(),
        "none",
    ),
    (
        "NFS-backed cluster",
        dict(storage_backend="nfs", nas_server="10.9.1.12", nas_path="/volume1/k8s",
             nas_backup_path="/volume2/backup1"),
        "nfs",
    ),
    (
        "a NAS with the database on longhorn is still a NAS — jg-jiahd's shape, "
        "and the reason db_storage_class is not the gate",
        dict(storage_backend="nfs", nas_server="10.9.2.13", nas_path="/volume1/k8s",
             nas_backup_path="/volume3/backup1",
             db_storage_class="longhorn", replicated_storage=True),
        "nfs",
    ),
    (
        "a NAS declared without storage_backend nfs still gets its backup",
        dict(nas_server="10.9.1.12", nas_backup_path="/volume2/backup1"),
        "nfs",
    ),
]

# The two live clusters that actually have a NAS sit on different volume
# numbers. Written out because the constant that broke #82 looked reasonable
# to everyone who only ever saw one of these.
FLEET_PATHS = {"10.9.1.12": "/volume2/backup1", "10.9.2.13": "/volume3/backup1"}


def main() -> int:
    plugin = load_plugin()
    failed = 0
    for name, extra, expected in CASES:
        data = dict(BASE, **extra)
        try:
            plugin.Plugin(data).data()
            got = data["nas_backup"]
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {name}\n        render raised {type(e).__name__}: {e}")
            failed += 1
            continue
        if got == expected:
            print(f"PASS  {name}\n        nas_backup = {got!r}")
        else:
            print(f"FAIL  {name}\n        expected {expected!r}, got {got!r}")
            failed += 1

    answers = set()
    for _, extra, _ in CASES:
        d = dict(BASE, **extra)
        plugin.Plugin(d).data()
        answers.add(d["nas_backup"])

    # A constant passes a same-answer suite. Require it to actually vary.
    if len(answers) < 2:
        print("\nFAIL  the derivation returned the same answer for every case —")
        print("      a value that never varies is not being computed from anything.")
        failed += 1

    # And require it to still be a string once YAML has had a look at it.
    # Two ways to fail that, and the type check is not redundant: a Python bool
    # is not in NOT_A_STRING, but Jinja renders it as `True`, which YAML 1.1
    # reads as a boolean just the same. Caught by exactly this line during the
    # negative-control run for this file.
    bad = sorted(
        (repr(a) for a in answers if not isinstance(a, str) or a in NOT_A_STRING),
        key=str,
    )
    if bad:
        print(f"\nFAIL  derived {bad}, which YAML does not read as a string —")
        print("      stringData rejects it and the consuming Secret never applies")
        print("      (ferry133/jg-base#16).")
        failed += 1

    # Each answer has to name a directory that exists in jg-base, or Flux
    # reports "path not found" and the backup Kustomization is red forever.
    print(f"\n(directories checked in jg-base: {sorted(answers)} — verify against"
          " kubernetes/apps/extras/*/postgres/backup/ when that repo changes)")

    # ---- the WHERE half (ferry133/jg-base#82) ----------------------------
    #
    # Refused rather than defaulted, and that is the whole point: a default is
    # the same defect one move later. /volume2/backup1 was a real path on a
    # real NAS, which is why it survived review in three manifests, and on the
    # other NAS it failed exactly like an unset path would -- silently, daily,
    # behind a healthy-looking CronJob.
    for server, path in sorted(FLEET_PATHS.items()):
        d = dict(BASE, nas_server=server, nas_path="/volume1/k8s",
                 nas_backup_path=path)
        try:
            plugin.Plugin(d).data()
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {server} + {path} raised {type(e).__name__}: {e}")
            failed += 1
            continue
        if d.get("nas_backup_path") != path:
            print(f"FAIL  {server}: declared {path}, render carries "
                  f"{d.get('nas_backup_path')!r} — the path was rewritten")
            failed += 1
        else:
            print(f"PASS  {server} keeps its own export {path}")

    # THE NEGATIVE CONTROL. This is jg-jiahd's cluster.yaml as it stands: a NAS,
    # and nothing saying where its backups go. It has to stop being accepted,
    # because what jg-base does with an empty path is mount nothing and say so
    # nowhere.
    d = dict(BASE, nas_server="10.9.2.13", nas_path="/volume1/k8s")
    try:
        plugin.Plugin(d).data()
    except KeyError as e:
        if "nas_backup_path" in str(e):
            print("PASS  a NAS with no backup export is refused, by name")
        else:
            print(f"FAIL  refused without naming the field: {e}")
            failed += 1
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  wrong exception: {type(e).__name__}: {e}")
        failed += 1
    else:
        print("FAIL  a NAS with no nas_backup_path was ACCEPTED — it renders an")
        print("      empty NAS_BACKUP_PATH, and an empty mount is as quiet as")
        print("      the wrong one was.")
        failed += 1

    # ...and not quietly borrowed from the neighbouring field. The backup share
    # is a separate export so it can be ShareSynced off-site on its own;
    # deriving it from nas_path would rebuild #82 with a tidier default.
    if "nas_backup_path" in d:
        print(f"FAIL  nas_path was reused as the backup export: "
              f"{d['nas_backup_path']!r}")
        failed += 1
    else:
        print("PASS  nas_path is not borrowed as the backup export")

    # A cluster with no NAS is asked for nothing. jg-janncotcc: a guard that
    # demanded a backup export from every cluster would block its render over
    # a share it does not have.
    d = dict(BASE)
    try:
        plugin.Plugin(d).data()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  a NAS-less cluster was blocked: {type(e).__name__}: {e}")
        failed += 1
    else:
        if d.get("nas_backup_path"):
            print(f"FAIL  no NAS, yet a backup export appeared: "
                  f"{d['nas_backup_path']!r}")
            failed += 1
        else:
            print("PASS  no NAS -> nothing demanded, nothing invented")

    # And the value has to reach cluster-secrets. Without this line every case
    # above can pass while no file emits the variable -- a guard proving a
    # field that goes nowhere, which is jgct#90 seen from the other side.
    tmpl = ROOT / ("templates/config/kubernetes/components/sops/"
                   "cluster-secrets.sops.yaml.j2")
    if not tmpl.is_file():
        print(f"FAIL  cannot find {tmpl}")
        failed += 1
    elif re.search(r'^[ \t]*NAS_BACKUP_PATH:[ \t]*"#\{[ \t]*nas_backup_path',
                   tmpl.read_text(), re.MULTILINE):
        print("PASS  cluster-secrets emits NAS_BACKUP_PATH from the field")
    else:
        print("FAIL  nothing emits NAS_BACKUP_PATH into cluster-secrets — the")
        print("      value stops at the plugin and jg-base substitutes nothing.")
        failed += 1

    print()
    if failed:
        print(f"{failed} case(s) failed.")
        print("Stuck 'nfs' turns an appliance's database Kustomization red; stuck")
        print("'none' stops every NAS cluster's dumps without anything going red.")
        print("A missing or borrowed nas_backup_path does the third thing: the")
        print("CronJob runs, reports healthy, and writes nowhere (jg-base#82).")
        return 1
    print(f"ok — {len(CASES)} derivation cases match (varies, stays a string), "
          f"and the backup export is per-NAS, demanded, and emitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assert this cluster's Longhorn backup selector agrees with its Longhorn.

`LONGHORN_BACKUP` picks a directory in jg-base:

    kubernetes/apps/base/storage/longhorn/backup/${LONGHORN_BACKUP:=none}

`nfs` renders a RecurringJob into longhorn-system. That is only meaningful on a
cluster that actually installs Longhorn, and the two facts come from different
places: the selector is derived from `longhorn_backup_target`, while whether
Longhorn is installed is `deploy_longhorn`, derived from `replicated_storage`
or `storage_backend`. Nothing forces them to agree.

`cue vet` cannot close this. It catches the outright contradiction
(`longhorn_backup_target` set together with `replicated_storage: false` --
measured, it reports "conflicting values true and false"), but not the case
that actually happens: `replicated_storage` simply absent. CUE sees an optional
field it may define as `true`, which is not an error, and plugin.py never reads
CUE's unified value anyway -- it reads cluster.yaml. Measured: target set,
`storage_backend: nfs`, `replicated_storage` absent renders
`deploy_longhorn=False` with `longhorn_backup=nfs`, and `cue vet` exits clean.

What that costs if unchecked: the per-user repo suspends `Kustomization/longhorn`,
jg-base's `longhorn-backup` selects ./nfs, and the RecurringJob is applied
against a CRD that no chart ever installed. The Kustomization goes Ready=False
and stays there, and the operator believes there is a nightly backup.

Runs against the RENDERED artifacts, after render-configs, for the same reason
check-backup-recipient.py does: the input someone meant to write and the output
that ships are different things, and only one of them reaches a cluster.

Exit 0 pass, 1 fail, 2 could not measure -- three outcomes, because a check
that cannot see its subject must not read as one that passed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SECRET = Path('kubernetes/components/sops/cluster-secrets.sops.yaml')
CLUSTER_KS = Path('kubernetes/flux/cluster/ks.yaml')

# Schemes longhorn-manager knows how to write to. A typo here does not fail at
# render or at apply -- the BackupTarget CR simply reports available: false,
# which looks the same as a NAS that is merely unreachable.
SCHEMES = ('nfs://', 'cifs://', 's3://', 'azblob://', 'gcs://')

# Values a YAML 1.1 parser reads as something other than a string. The selector
# lands in stringData, and kustomize does not keep the quotes around the
# placeholder it is substituted into (ferry133/jg-base#16).
NOT_A_STRING = {
    '', '~', 'null', 'Null', 'NULL',
    'true', 'True', 'TRUE', 'false', 'False', 'FALSE',
    'yes', 'Yes', 'YES', 'no', 'No', 'NO',
    'on', 'On', 'ON', 'off', 'Off', 'OFF',
}


def value_of(text: str, key: str) -> str | None:
    m = re.search(rf'^\s+{re.escape(key)}:\s*(.*?)\s*$', text, re.M)
    if m is None:
        return None
    return m.group(1).strip().strip('"').strip("'")


def longhorn_is_suspended(ks_text: str) -> bool:
    """True if the rendered cluster ks.yaml suspends Kustomization/longhorn.

    The per-user repo suspends by patching, one `- patch: |-` block per
    disabled Kustomization. Matching on the block keeps `longhorn` from being
    confused with any other name that merely contains it.
    """
    for block in ks_text.split('- patch: |-')[1:]:
        head = block.split('- patch: |-')[0]
        if 'suspend: true' not in head:
            continue
        if re.search(r'^\s+name:\s*longhorn\s*$', head, re.M):
            return True
    return False


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    secret, cluster_ks = root / SECRET, root / CLUSTER_KS

    missing = [p for p in (secret, cluster_ks) if not p.is_file()]
    if missing:
        for p in missing:
            print(f'COULD NOT MEASURE  {p} does not exist')
        print('\nRun this after `render-configs`. Reporting "could not measure"')
        print('rather than passing: an absent artifact is not a correct one.')
        return 2

    secret_text = secret.read_text()
    selector = value_of(secret_text, 'LONGHORN_BACKUP')
    target = value_of(secret_text, 'LONGHORN_BACKUP_TARGET')

    if selector is None:
        print('COULD NOT MEASURE  LONGHORN_BACKUP is not in the rendered secret.')
        print('  This repo\'s templates/ predate ferry133/jg-base#7. A per-user')
        print('  repo carries its own copy of templates/, and `task configure`')
        print('  exits 0 either way, so this is exactly the state that reads')
        print('  like a pass. Sync templates/ from jg-cluster-template first.')
        return 2

    failed = []

    if selector not in ('nfs', 'none'):
        failed.append(
            f'LONGHORN_BACKUP is {selector!r}; jg-base only has directories '
            'backup/nfs and backup/none, and Flux reports "path not found" '
            'for anything else')
    if selector in NOT_A_STRING:
        failed.append(
            f'LONGHORN_BACKUP is {selector!r}, which YAML does not read as a '
            'string -- stringData rejects it and the whole Secret fails to '
            'apply (ferry133/jg-base#16)')

    has_target = bool(target)
    if has_target and selector != 'nfs':
        failed.append(
            f'a backup target is set ({target}) but LONGHORN_BACKUP is '
            f'{selector!r}, so no RecurringJob renders: Longhorn would have a '
            'target and never write to it')
    if not has_target and selector == 'nfs':
        failed.append(
            'LONGHORN_BACKUP is "nfs" with no LONGHORN_BACKUP_TARGET, so the '
            'RecurringJob renders and fails nightly against an unset target')

    if has_target and not target.startswith(SCHEMES):
        failed.append(
            f'LONGHORN_BACKUP_TARGET {target!r} has no scheme Longhorn '
            f'accepts ({", ".join(SCHEMES)}); the BackupTarget CR reports '
            'available: false, which looks the same as an unreachable NAS')

    suspended = longhorn_is_suspended(cluster_ks.read_text())
    if selector == 'nfs' and suspended:
        failed.append(
            'LONGHORN_BACKUP is "nfs" but this cluster suspends '
            'Kustomization/longhorn, so the RecurringJob is applied against a '
            'CRD no chart installs. Set replicated_storage: true (or '
            'storage_backend: "replicated") if Longhorn is wanted here, or '
            'drop longhorn_backup_target if it is not')

    print(f'LONGHORN_BACKUP        = {selector!r}')
    print(f'LONGHORN_BACKUP_TARGET = {target!r}')
    print(f'Kustomization/longhorn = {"suspended" if suspended else "active"}')
    print()

    if failed:
        for f in failed:
            print(f'FAIL  {f}')
        return 1

    if selector == 'none':
        print('ok - no Longhorn backup configured; jg-base renders zero objects')
        print('     and the chart render is byte-identical to a cluster that')
        print('     never had this variable (measured with helm template).')
    else:
        print('ok - backup target set, selector agrees, Longhorn is installed.')
        print()
        print('     NOT checked here, and not checkable from a template repo:')
        print('     whether the export accepts writes from longhorn instance-manager,')
        print('     and whether a backup has ever been restored. A backup target')
        print('     that has never restored is a hypothesis.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

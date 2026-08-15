## MODIFIED Requirements

### Requirement: Backup scope covers what cannot be reconstructed

Backups SHALL include the database tier and the complete state of the cluster's agent — its accumulated memory, its session history, and any working material that is not reconstructible. Content already durable elsewhere — Kubernetes manifests in the Git repository, cluster state rebuildable from that repository, repository clones, package directories, build output, caches — MUST NOT be included.

The agent is the operator's presence at the customer site; recovering it partially is worse than not recovering it at all, because a partial agent still reads as authoritative while silently missing history. Scope SHALL therefore be decided by content, not by volume: excluding a whole volume to avoid its reconstructible contents also discards the memory stored beside them.

The agent's authentication material SHALL be included. It belongs to the operator rather than to the customer, the archive is encrypted to the cluster's own key before it leaves, and the alternative — an agent that arrives unable to authenticate — defeats unattended recovery. Revocation is handled by invalidating the source side at takeover, not by withholding the material from the archive.

Session history SHALL be subject to a retention limit. It grows without bound and is the largest component of the archive.

#### Scenario: Database tier captured

- **WHEN** a backup run completes
- **THEN** the archive contains a dump of every database in the cluster

#### Scenario: Agent state captured

- **WHEN** a backup run completes
- **THEN** the archive contains the agent's memory, its session history within the retention limit, and its authentication material

#### Scenario: Reconstructible content excluded

- **WHEN** a backup run completes
- **THEN** the archive contains no Git-tracked Kubernetes manifests, no repository clones, no package directories, and no build output or caches

#### Scenario: Archive is sufficient to reconstitute the agent

- **WHEN** an archive is restored onto a cluster other than the source
- **THEN** the agent starts with the source cluster's memory and history available, with nothing copied from the source cluster at restore time

### Requirement: Restore is verified, not assumed

An untested backup is not a backup. A restore drill SHALL be performed on a scratch cluster and SHALL be the acceptance criterion for this capability.

#### Scenario: Restore drill succeeds

- **WHEN** a backup archive is restored onto a freshly provisioned scratch cluster using only the archive and the escrowed `age.key`
- **THEN** the database contents match the source cluster at backup time, compared table by table, and the restored agent's memory matches the source

#### Scenario: Restore procedure is documented

- **WHEN** an operator needs to restore an appliance
- **THEN** a written restore procedure exists that was followed verbatim during the drill

## ADDED Requirements

### Requirement: Agent state is archived from where it lives

The component that archives agent state SHALL run where those volumes can be mounted, and SHALL write to the same destination, under the same prefix, encrypted to the same key as the database backup. Relocating the database backup to reach those volumes is not required and SHALL NOT be done: a backup job belongs with monitoring, and moving it to satisfy a mount is letting an implementation detail decide where things live.

#### Scenario: Both components land in one archive set

- **WHEN** a scheduled backup completes
- **THEN** the database dump and the agent state archive are both present at the same destination prefix, encrypted to the same recipient, and identifiable as one set

#### Scenario: Partial failure is not averaged away

- **WHEN** one of the two components succeeds and the other fails
- **THEN** the daily check reports each component's freshness separately, and the cluster is not reported as backed up

### Requirement: Backups can be taken outside the schedule

The backup pipeline SHALL support an on-demand run that produces an archive identical in contents, encryption, and destination to a scheduled one. Migration and handover happen at a moment the schedule did not anticipate, and waiting for the next scheduled run means handing over a state that is up to a day old.

The on-demand path SHALL be the same job definitions as the scheduled ones. A separate path would drift, and the drift would be discovered when the archive is needed.

#### Scenario: On-demand run produces an equivalent archive

- **WHEN** an operator triggers a backup outside the schedule
- **THEN** the resulting archive set is produced by the same job definitions, encrypted to the same recipient, and written to the same destination as a scheduled run

#### Scenario: On-demand failure is not silent

- **WHEN** an on-demand backup fails
- **THEN** it exits non-zero and the failure is visible to the caller, rather than reporting success with an empty upload

#### Scenario: Freshness reporting is unaffected

- **WHEN** an on-demand backup completes
- **THEN** the daily check's backup-age reporting treats it the same as a scheduled run

## ADDED Requirements

### Requirement: Storage tier is chosen by data type, not by size

Workloads SHALL be assigned a storage tier according to their access semantics. Anything relying on `fsync` durability and file locking — PostgreSQL, etcd, embedded databases, agent memory stores — MUST use block-backed storage. Bulk media, file shares, and backup targets MAY use NFS.

#### Scenario: Database uses block-backed storage
- **WHEN** a PostgreSQL PVC is provisioned under any profile
- **THEN** its storage class is block-backed (`local-path`, or a CSI block class where one is configured), never an NFS class

#### Scenario: Media uses NFS when available
- **WHEN** a bulk media or file-share PVC is provisioned on a cluster with `storage_backend: nfs`
- **THEN** it is provisioned from the NFS class

#### Scenario: Capacity pressure does not move a database to NFS
- **WHEN** a database outgrows local disk capacity
- **THEN** the remedy is larger local capacity or a block-mode CSI class backed by the NAS, and moving the database onto an NFS class is rejected

### Requirement: Default storage class follows the profile

Each profile SHALL supply a default storage class so that PVCs without an explicit class resolve correctly. Under `appliance` the default SHALL be `local-path`. Under `prosumer` and `full` the default SHALL follow `storage_backend`.

#### Scenario: Appliance defaults to local-path
- **WHEN** a PVC without an explicit storage class is created on an appliance cluster
- **THEN** it binds to a `local-path` volume

#### Scenario: NFS backend supplies the default
- **WHEN** a PVC without an explicit storage class is created on a cluster with `storage_backend: nfs`
- **THEN** it binds via the NFS provisioner, as today

### Requirement: No PVC depends on manual pre-provisioning

Every PVC shipped in `jg-base` SHALL be dynamically provisionable. An empty-string `storageClassName` disables dynamic provisioning and leaves the claim Pending forever on a cluster with no matching pre-created PersistentVolume; this MUST be corrected.

#### Scenario: Postgres backup PVCs bind on an appliance
- **WHEN** the `default/postgres` extra is deployed on an appliance cluster with no pre-created PersistentVolumes
- **THEN** its backup PVCs bind successfully rather than remaining Pending

#### Scenario: Shipped PVCs are inspectable for the defect
- **WHEN** all PVC manifests in `jg-base` are inspected
- **THEN** none declares `storageClassName: ""`

### Requirement: Agent workspace and agent memory have different durability

The claude-code workspace holds reconstructible working files and MAY live on node-local storage. Agent memory holds accumulated per-customer context that cannot be reconstructed and SHALL be stored in the database tier so that it is covered by database backups.

#### Scenario: Workspace on local storage
- **WHEN** a claude-code instance is deployed with no `nas_coding_path` configured
- **THEN** its workspace PVC is provisioned from the profile's default class and the deployment succeeds

#### Scenario: Agent memory survives workspace loss
- **WHEN** the workspace volume is destroyed and the instance is recreated
- **THEN** accumulated agent memory is still available, having been stored in the database tier

#### Scenario: NAS coding path remains available
- **WHEN** `nas_coding_path` is configured on a `prosumer` or `full` cluster
- **THEN** the workspace is mounted from NFS as today, unchanged by this requirement

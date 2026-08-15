## ADDED Requirements

### Requirement: The office rescue instance holds no privilege over the office cluster

An agent instance run outside the customer site to operate a customer's cluster SHALL NOT hold cluster-admin over the cluster hosting it. Its privileges within the hosting cluster SHALL be confined to its own namespace; its reach into the customer cluster SHALL come from that customer's credentials alone.

The customer-side instance is deliberately cluster-admin — that is what makes it a support channel of last resort, and that privilege belongs to the cluster it was created for. An instance recreated elsewhere carries the agent's memory, not the agent's standing in a cluster it no longer runs in.

#### Scenario: Rescue instance cannot act on its host

- **WHEN** the rescue instance attempts an operation outside its own namespace in the hosting cluster
- **THEN** the request is denied by RBAC

#### Scenario: Rescue instance acts on the customer cluster

- **WHEN** the rescue instance uses the customer's service-account kubeconfig
- **THEN** it can operate that customer's cluster with the privileges that credential carries

### Requirement: A rescue instance is reconstituted from the archive, not transferred live

The rescue instance SHALL be created from the customer's archive using the escrowed `age.key`, with no live transfer from the customer cluster required at any point. Requiring a live transfer would make the capability unavailable in exactly the case it exists for: a cluster that is unreachable or gone.

Reconstitution SHALL yield an agent equivalent to the source — same memory, same history within the retention limit, able to authenticate — not a fresh agent that merely has access to the same cluster.

#### Scenario: Reconstitution needs only the archive and the key

- **WHEN** an operator reconstitutes a rescue instance using only an archive retrieved from the backup destination and the escrowed `age.key`
- **THEN** the instance starts with the source cluster's memory and history, with no access to the customer cluster required

#### Scenario: The reconstituted agent is the same agent

- **WHEN** the rescue instance is asked about work done on the source cluster before the archive was taken
- **THEN** it answers from the restored memory and history, not from an empty state

### Requirement: Exactly one instance is authoritative at a time

When a rescue instance takes over, the customer-side instance SHALL cease to be authoritative from that moment, and its authentication material SHALL be invalidated at the source as part of the takeover. Returning work to the customer cluster SHALL be done by restoring from an archive taken on the rescue side. Merging the two states SHALL NOT be attempted.

Invalidating at takeover is what bounds the window in which the same credential is live in two places; it is one action with the handover, not a separate cleanup step that can be forgotten.

#### Scenario: Takeover invalidates the source side

- **WHEN** a rescue instance takes over for a customer cluster
- **THEN** the customer-side instance's authentication material is invalidated and the takeover is recorded with its time

#### Scenario: Handback is a restore, not a merge

- **WHEN** work returns to the customer cluster after a rescue period
- **THEN** the customer-side state is replaced from a rescue-side archive, with no attempt to reconcile divergent entries

### Requirement: Remote work proceeds without reaching the customer cluster

Changing a cluster's configuration is a Git push that the cluster's own GitOps reconciler pulls. The rescue instance SHALL be able to complete the change-making half of any migration with no network path to the customer cluster. Verification SHALL still be required before a step is considered complete, and MAY be deferred until a path exists.

This is what makes the capability survive an Omni or SideroLink outage, which is one of the cases that sends work to the office in the first place.

#### Scenario: Change lands with the cluster unreachable from the office

- **WHEN** the rescue instance edits `cluster.yaml`, renders, and pushes while the customer cluster is unreachable from the office
- **THEN** the customer cluster applies the change on its next reconcile, its outbound path to the Git host being the only connectivity required

#### Scenario: Unverified work is not reported as done

- **WHEN** a migration step has been pushed but its verification could not be run
- **THEN** the step is reported as pushed-but-unverified, and the migration is not recorded as complete

### Requirement: Reconstitution is verified, not assumed

Reconstituting a rescue instance SHALL be exercised end to end, using an archive and an escrowed key copy rather than any working copy held in a repository, and the result SHALL be compared against the source record by record. A written procedure SHALL exist that was followed verbatim during that exercise.

Using the escrowed copy is the point: a truncated key copy reads exactly like a working one until the day it is needed.

#### Scenario: Drill reproduces the source state

- **WHEN** a rescue instance is reconstituted from an archive using only the escrowed key copy
- **THEN** each restored database table matches the source's row counts and contents at backup time, and the restored agent memory matches the source

#### Scenario: Procedure exists and matches what was done

- **WHEN** an operator needs to reconstitute a rescue instance
- **THEN** a written procedure exists whose steps are the ones the drill actually executed

# Replicated block storage (Longhorn)

`storage_backend: "replicated"` deploys Longhorn, so a database on a multi-node
cluster is not pinned to whichever node scheduled it first.

**It does not work until the nodes are prepared.** Longhorn needs two Talos
system extensions and a mount with shared propagation — none of which a
Kubernetes manifest can install. Deploy it without them and the pods start,
report healthy, and fail to attach any volume.

## Is it worth it here?

Ask before installing. Longhorn is a distributed storage system to maintain, and
the alternative is not nothing:

| | pinned local-path + backups | Longhorn |
|---|---|---|
| Node dies | restore from last night's dump onto another node | volume rebuilds from a surviving replica |
| RPO | up to 24h | 0 |
| RTO | ~15 min, manual | seconds, automatic |
| Cost | none beyond the backup already running | ~1 GB RAM per node, a system to upgrade and watch |

For jg-jiahd — three nodes, an 8.7 MB database, a verified daily restore path —
the honest answer is that pinning plus backups is defensible. Longhorn earns its
place when the RPO matters, when the data is large enough that restoring is slow,
or when nodes are rebooted often enough that manual recovery stops being rare.

There is also a third option this stack does not implement: a CSI driver serving
**block** volumes from the NAS over iSCSI. That keeps one copy of the data on
hardware that already has RAID, gives correct fsync semantics, and allows the pod
to move — without a second replication layer. It needs the same iSCSI extension
below.

## Preparing the nodes

Both extensions, on every node:

| extension | why |
|---|---|
| `siderolabs/iscsi-tools` | Longhorn attaches volumes as iSCSI devices |
| `siderolabs/util-linux-tools` | `fstrim`, used to reclaim space in volumes |

And a mount for the data path, with `rshared` propagation so Longhorn's
containers can see mounts the node makes:

```yaml
machine:
  kubelet:
    extraMounts:
      - destination: /var/lib/longhorn
        type: bind
        source: /var/lib/longhorn
        options: [bind, rshared, rw]
```

`/var` is the only writable filesystem Talos keeps across upgrades; a data path
anywhere else is wiped by the next one.

### Omni-provisioned clusters

Both changes belong to the machine's configuration in Omni:

1. Add the two extensions to the schematic, which produces a new schematic ID.
2. Add the `extraMounts` block above as a MachineConfigPatch on the cluster.
3. Roll the nodes onto the new schematic — **one at a time**, confirming the
   cluster is healthy before moving to the next.

Changing the schematic reboots the node. On a three-node cluster that is
survivable; confirm etcd has quorum before starting the next one.

### Manual Talos clusters

Add to `nodes.yaml` per node and to the controller patch respectively, then
`task talos:apply-node IP=<ip>` and `task talos:upgrade-node IP=<ip>`.

## Verify before enabling

From any node's context, after the extensions are in place:

```sh
kubectl get nodes -o json \
  | jq -r '.items[] | "\(.metadata.name)  \(.status.nodeInfo.osImage)"'
```

Then enable `storage_backend: "replicated"`, re-render and push. Longhorn's own
readiness is the real check:

```sh
kubectl -n longhorn-system get pods
kubectl get storageclass longhorn
```

## Moving the database onto it

Installing Longhorn does not move anything. Set `db_storage_class: "longhorn"`
explicitly, and remember a PVC's `storageClassName` is immutable — the move is a
dump and restore, the same procedure as any other class change. Forgetting is
not silent: the database stays on a node-local class and validation asks for
`accept_node_pinning`, naming the thing that was missed.

## Replica count

Two, not three, on a three-node cluster. One node can be down or draining while
the volume still has a copy and somewhere to rebuild onto. Three replicas costs
three times the space to protect data measured in megabytes, and a third copy
does not help against the failure that actually threatens a home cluster — the
whole site.

That is what the off-site backup is for, and it is still required.

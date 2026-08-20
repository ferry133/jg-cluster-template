# age.key escrow

`age.key` is the only thing that can read this cluster's backups. They are
encrypted to the cluster's own public key, which is what keeps them private from
whoever owns the R2 account — and what makes the key irreplaceable.

On a single-node appliance the key lives on the one disk whose failure the
backups exist to survive. **An unescrowed key means the off-site backups are
ciphertext nobody can open**, which is worse than having none, because it looks
like protection right up until the morning it is needed.

Validation refuses to render an appliance until `age_key_escrowed: true` is set
in `cluster.yaml`. That field is not defaulted: it has to be written by whoever
did the escrow, for the same reason `accept_node_pinning` is not defaulted.

## What to escrow

| | |
|---|---|
| `age.key` | the private key; without it nothing else here matters |
| `cluster.yaml` | not secret-free — holds Cloudflare and R2 credentials |
| `kubeconfig` / `kubeconfig-sa` | cluster access, replaceable but slow to rebuild |

The per-user repository does **not** need escrowing: it is on GitHub, and it
holds only what is already encrypted with the same key.

## Where

Somewhere that survives the appliance and is not the appliance:

- a password manager entry on the operator's account, or
- an encrypted archive in a location independent of the R2 bucket

Do not put it in the same R2 bucket as the backups. Any store that fails or is
lost together with the thing it protects is not a second copy.

## Verifying the escrow before declaring it

Restore-test the copy, not the original. An escrowed key that was truncated on
the way in reads exactly like one that works:

```sh
# from the escrowed copy, not from the cluster
age-keygen -y escrowed-age.key
```

It must print the same public key as the `age:` line in `.sops.yaml`. If it does
not, the escrow is wrong and `age_key_escrowed: true` would be a false
statement.

## Escrowing every cluster at once

`scripts/escrow-secrets.sh` does the above for every cluster on the operator's
machine in one pass, and then proves the result opens. Run it from anywhere:

```sh
scripts/escrow-secrets.sh --dry-run   # what would be collected, no crypto, no upload
scripts/escrow-secrets.sh             # collect, encrypt, upload, read back, verify
```

**It discovers clusters by looking for `age.key` + `cluster.yaml`, not from a
list.** A list is a fixture: it cannot report the cluster nobody added to it, and
the omission renders as a clean run over the clusters that were remembered. The
first run found 8 such directories on a machine where the hand-written list had
4 — `jg-jiahd.keep`, `jgt-omni-accept`, `jgt-talos-accept` and `jgtest` were all
holding keys nobody had counted.

Which of them get escrowed is a separate decision from which get looked at.
`ESCROW_CLUSTERS` (default `jcom jg-jiahd` — the two holding real data; the rest
are test beds) narrows what is collected, and **everything discovered and not
collected is printed by name**:

```
[12:29:01Z] escrowing 2: jcom jg-jiahd
[12:29:01Z] found but NOT escrowed (6): genie1 jg-jiahd.keep jgt-appliance jgt-omni-accept jgt-talos-accept jgtest
       If any of those is not a test bed, add it to ESCROW_CLUSTERS.
```

Deciding not to escrow something is fine. Not noticing it exists is the failure
this arrangement is shaped to prevent: a real cluster nobody added to the list
appears in that second line rather than in no line at all.

`jg-jiahd.keep` derives a different public key from `jg-jiahd`, so it is not a
stale copy of it — worth resolving before it is written off as one.

Three choices are built in rather than left to the operator:

| | why |
|---|---|
| **a passphrase, not a keypair** | a keypair protecting `age.key` would itself need escrowing, and that recursion has no bottom. `age -p` reads from the terminal; the script never sees, stores, or passes it |
| **its own bucket** | the rule above forbids the same bucket as the backups. The stated reason is correlated loss; the sharper one is correlated access — one bucket holding both the ciphertext and the key that opens it is plaintext with extra steps |
| **verification reads back from the store** | decrypting the local copy proves the local copy works, which was never in question. A truncated upload reads exactly like a good one |

### Exit codes

`0` every restored key matched · `1` at least one mismatched · **`2` at least one
could not be told either way** — a missing `age.key` in the restored archive, or
a repo with no `age:` line to compare against. Two empty strings compare equal,
so a check with nothing on either side would otherwise report success; `2` exists
so that never becomes a recorded pass.

### The bucket

Separate from the backup buckets. On MinIO, the service account needs an
inline policy — and it **must include the multipart actions**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:ListBucketMultipartUploads"],
      "Resource": ["arn:aws:s3:::fleet-escrow"] },
    { "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject",
                 "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
      "Resource": ["arn:aws:s3:::fleet-escrow/*"] }
  ]
}
```

Without the last two, an interrupted upload strands parts the key can neither
list nor abort, and nothing in `aws s3 ls` or the log will say so. Measured on
2026-08-20 against a policy that omitted them: `ListParts`,
`AbortMultipartUpload` and `ListBucketMultipartUploads` all returned 403 while
the happy path succeeded — so a small test upload passes and the failure waits
for a large one. Give the bucket a lifecycle rule expiring incomplete multipart
uploads as well; a server-side rule holds regardless of what the client may do.

### Credentials

`~/.config/fleet-escrow/minio.env`, mode `600` — the script refuses any other
mode:

```sh
MINIO_ENDPOINT=https://minio.janncot.com
MINIO_BUCKET=fleet-escrow
MINIO_ACCESS_KEY_ID=...
MINIO_SECRET_ACCESS_KEY=...
```

The passphrase does **not** go in this file. If it did, the store and the thing
that opens it would travel together, which is the rule at the top of this page.

## Handover

Handing the cluster to the customer means handing over `age.key`. From that
moment the operator's copy is a second key to someone else's data — either
destroy it, or say plainly that it still exists. "The customer can take the keys
back" only means something if the operator's copy is accounted for.

# Restoring from an off-site backup

The `offsite-backup` CronJob (`monitoring`) dumps every database in the cluster,
encrypts the archive to the cluster's own age public key, and uploads it to
Cloudflare R2. This page is the other half: getting the data back.

**Scope.** Escrowing `age.key` and verifying the escrowed copy is
[`age-key-escrow.md`](age-key-escrow.md) — that procedure is not repeated here.
Moving a live database between storage classes is
[`combinations.md` §7.4](../deploy/combinations.md) — a different operation that
happens to share the words "dump" and "restore".

**Status.** Steps 1–4 below were executed on jgt-appliance on 2026-08-15/16 and
the outputs are the observed ones. **Step 5, the restore itself, has never been
run** — see [What has not been proven](#what-has-not-been-proven). Read that
section before treating anything here as a tested recovery path.

## What the archive contains

As implemented today: a `pg_dump` of every database the job finds, and nothing
else. Kubernetes manifests are excluded deliberately — the authoritative copy is
in Git, and restoring them from an archive only restores an older snapshot.

The agent's volumes (`claude-config`, `claude-workspace` in `claudecode`) are
**not** in the archive. Extending the scope to cover them is
`agent-state-portability`; until that lands, an appliance restored from an
archive comes back with its databases and without its agent's history.

## Triggering a backup

Scheduled: 02:00 Asia/Taipei, ahead of the 08:00 daily check so a failure is
reported the same day.

On demand — the same job definition, not a hand-written equivalent:

```sh
kubectl create job -n monitoring drill-backup --from=cronjob/offsite-backup
kubectl logs -n monitoring job/drill-backup
```

Observed on jgt-appliance:

```
dumping db/postgres
  13439 bytes
encrypted: 2362 bytes
uploaded s3://jgt-appliance-backup/jgt-appliance/jgt-appliance-20260815T015801Z.tar.gz.age
```

`nothing to back up` with exit 0 is **not** proof that the cluster has no
databases. That was the exact message D46 produced while the script was broken
upstream of the dump, and two clusters reported success daily while uploading
zero bytes for weeks. If you see it, verify against the cluster before believing
it.

## The drill, as executed

### 1. Seed known data

A throwaway postgres in namespace `db`, on `emptyDir` — deliberately no PVC, so
the drill exercises the archive path and not storage provisioning:

```sh
kubectl exec -n db deploy/postgres -- psql -U drill -d drill -v ON_ERROR_STOP=1 -c "
CREATE TABLE episodes (id serial PRIMARY KEY, note text, created_at timestamptz DEFAULT now());
CREATE TABLE knowledge (id serial PRIMARY KEY, topic text, body text);
INSERT INTO episodes (note) SELECT 'drill-episode-' || g FROM generate_series(1,137) g;
INSERT INTO knowledge (topic, body) SELECT 'topic-' || g, repeat('x', 64) FROM generate_series(1,42) g;"
```

Record the baseline **before anything else**. This is what the restore is
compared against, and reconstructing it afterwards from the restored copy proves
nothing:

```
episodes  = 137
knowledge = 42
md5(string_agg(note,',' ORDER BY id)) = 8127c5b3f3fc3a84fee748b49f1364d1
```

### 2. Run the real CronJob

Use `--from=cronjob/offsite-backup` as above. A hand-written equivalent tests a
script nobody runs; the point of the drill is the job that runs nightly.

### 3. Retrieve using the R2 credentials alone

An ad-hoc pod with `aws-cli` and the four `backup_r2_*` values, streaming the
object out and base64-decoding it locally:

```sh
aws s3 cp --endpoint-url "$BACKUP_R2_ENDPOINT" \
  "s3://${BACKUP_R2_BUCKET}/${CLUSTER_NAME}/${ARCHIVE}" - | base64 -w0
```

This leg needs nothing from the source cluster, which is the property that makes
it a recovery path rather than a backup check.

### 4. Prove the ciphertext is opaque

```
head -c 40                                     → age-encryption.org/v1
grep -c drill-episode | topic- | episodes |
      knowledge | CREATE                       → 0, 0, 0, 0, 0
```

This re-establishes on a real archive what task 7.3 established on a synthetic
string: whoever holds the R2 credentials holds ciphertext and nothing else.

### 5. Restore — procedure written, **never executed**

The restore needs the **escrowed** copy of `age.key`, and the escrow mechanism
is not implemented, so there is no copy to test against. Deferred deliberately
on 2026-08-16.

Use the escrowed copy, never the working copy in the repo.
[`age-key-escrow.md`](age-key-escrow.md) requires it for a reason that applies
exactly here: a truncated key copy reads identically to a good one, right up to
the moment it is the only one left. jgt-appliance declares
`age_key_escrowed: true` on nobody's authority.

```sh
age --decrypt -i <escrowed-age.key> "$ARCHIVE" | tar -xzf - -C <workdir>
```

Then, per database, **in this order**:

1. **Create the roles the dump references, first.** A `pg_dump` restore does not
   create them. Without them every `OWNER TO` fails while the tables are still
   created — so the restore looks like it worked, and the objects end up owned by
   `postgres`. Found on jg-jiahd during task 6.9, where the missing role was
   `linebot`.
2. `psql -v ON_ERROR_STOP=1 -f <dump>.sql` into the target database.
3. Compare against the baseline **table by table** — row counts and content
   digest, not a spot check.

If the restore target's storage class differs from the source, settle that
**before** deleting any PVC:

```sh
flux reconcile kustomization cluster-secrets --with-source
kubectl get secret cluster-secrets -n flux-system \
  -o jsonpath='{.data.DB_STORAGE_CLASS}' | base64 -d; echo
```

A push is not a reconcile. jcom lost a PVC to that window: Flux rebuilt it from
the not-yet-updated `cluster-secrets`, and `storageClassName` is immutable, so
the rebuilt PVC was wrong in the same way and had to be deleted again (D38).
**Deleting a PVC is a stop-and-ask step**, whatever else was already agreed.

## Retention: what it actually does today

`BACKUP_RETAIN_DAYS` (default 30) **has never had any effect**. The image is
alpine, busybox `date` rejects `-d '30 days ago'`, and the fallback set the
cutoff to today — so every run pruned every archive except its own. Measured on
jgt-appliance on 2026-08-16, the first run that ever got as far as pruning: the
first two archives this system ever produced were deleted the day after they
were written, with `KEEP` at 30.

The real defect is the direction of the fallback: "could not work out the cutoff"
became "delete everything before today". **The safe fallback on a retention path
is to keep, not to delete.** A fix (`date -d @<epoch>`, the one spelling busybox
and GNU both accept) is under review as `ferry133/jg-base#1` — `monitoring/backup`
belongs to jg-base — and is not yet on any cluster. Until it reconciles:

> **Do not plan a restore around an archive older than about a day.** Check what
> is actually in the bucket before assuming a specific date exists.

## What has not been proven

Steps 1–4 are executed and their outputs above are observed. Everything below is
still open:

| Not proven | Tracked as |
|---|---|
| That any archive can be decrypted with an **escrowed** key copy | `deployment-profiles` 8.3 |
| That a restored database matches the source table by table | `deployment-profiles` 8.3 |
| That jgt-appliance's `age_key_escrowed: true` is true | `deployment-profiles` 8.3 |
| That retention keeps anything beyond the current day | `ferry133/jg-base#1` · `deployment-profiles` 8.3c |
| That the agent's history survives a total loss | `agent-state-portability` |

A restore procedure that has been written but not run is a hypothesis. Treat
this page as one until the table above is empty.

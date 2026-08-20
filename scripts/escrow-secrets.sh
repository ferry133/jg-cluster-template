#!/usr/bin/env bash
# escrow-secrets.sh — collect the per-cluster files that exist nowhere else,
# encrypt them under a passphrase, upload them, and then prove the uploaded copy
# opens.
#
# The files this collects (age.key, cluster.yaml, kubeconfig, the tunnel
# credential) are in neither git nor the database dumps. Losing the machine they
# sit on loses them. docs/operations/age-key-escrow.md says what to escrow and
# why; this is the mechanised version of it, across every cluster on this
# machine rather than one at a time.
#
# Three rules are built in rather than left to the operator:
#
#   1. A passphrase, not a keypair. A keypair used to protect age.key would
#      itself need escrowing, and that recursion has no bottom. `age -p` reads
#      the passphrase from the terminal; nothing here ever sees it, stores it,
#      or passes it as an argument.
#
#   2. A store separate from the backups. age-key-escrow.md forbids putting the
#      key in the same bucket as the archives it decrypts. The stated reason is
#      correlated loss; the sharper one is correlated access — whoever can read
#      that bucket would hold the ciphertext and the key that opens it, which is
#      plaintext with extra steps. Hence its own bucket.
#
#   3. Verification reads back what was uploaded. Checking the local copy proves
#      the local copy works, which was never in doubt. A truncated upload reads
#      exactly like a good one until the morning it is needed.
#
# Usage:
#   scripts/escrow-secrets.sh                 # auto-discover under ~/coding
#   scripts/escrow-secrets.sh DIR [DIR...]    # explicit cluster directories
#   scripts/escrow-secrets.sh --dry-run       # collect and report, no crypto, no upload
#
# Credentials: reads MINIO_* from a file, default ~/.config/fleet-escrow/minio.env
# (mode 600). See docs/operations/age-key-escrow.md for the bucket policy — it
# must include the multipart actions, or uploads above 8 MB fail while small
# test uploads succeed.

set -uo pipefail

WORKSPACE="${WORKSPACE:-$HOME/coding}"
ENV_FILE="${FLEET_ESCROW_ENV:-$HOME/.config/fleet-escrow/minio.env}"
DRY_RUN=0

# Files taken from each cluster directory. Ordered by how irreplaceable they
# are, which is also the order the report prints them.
SECRET_FILES=(
  age.key                   # without this nothing else in the backup matters
  cluster.yaml              # the rendering input; holds every token in plaintext
  cloudflare-tunnel.json    # issued once at tunnel creation, not reissuable
  github-deploy.key
  github-push-token.txt
  kubeconfig
)
# Whole directories taken if present, minus junk.
SECRET_DIRS=(config.gen)

die() { printf 'FATAL: %s\n' "$*" >&2; exit 1; }
log() { printf '[%s] %s\n' "$(date -u '+%H:%M:%SZ')" "$*"; }

for a in "$@"; do [[ "$a" == "--dry-run" ]] && DRY_RUN=1; done
ARGS=(); for a in "$@"; do [[ "$a" == "--dry-run" ]] || ARGS+=("$a"); done

for t in age age-keygen tar curl; do
  command -v "$t" >/dev/null 2>&1 || die "$t not found in PATH"
done
curl --help all 2>/dev/null | grep -q -- '--aws-sigv4' \
  || die "this curl has no --aws-sigv4; install curl >= 7.75 or use mc"

# ── Which clusters ───────────────────────────────────────────────────────────
# Discovery is by "has the files worth escrowing", not by a hand-written list.
# A list is a fixture, and a fixture cannot report the cluster nobody added to
# it — the omission would show up as a clean run over the clusters that were
# remembered.
CLUSTERS=()
if [[ ${#ARGS[@]} -gt 0 ]]; then
  CLUSTERS=("${ARGS[@]}")
else
  for d in "$WORKSPACE"/*/; do
    [[ -f "${d}age.key" && -f "${d}cluster.yaml" ]] && CLUSTERS+=("${d%/}")
  done
fi
[[ ${#CLUSTERS[@]} -gt 0 ]] || die "no cluster directories found under $WORKSPACE"

log "clusters: ${#CLUSTERS[@]}"

# ── Stage ────────────────────────────────────────────────────────────────────
umask 077
STAGE="$(mktemp -d)"; VERIFY="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$VERIFY"' EXIT
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
ROOT="$STAGE/fleet-escrow-$STAMP"; mkdir -p "$ROOT"
MANIFEST="$ROOT/MANIFEST.txt"

{
  echo "fleet escrow $STAMP"
  echo "host $(hostname -s)"
  echo
  echo "# cluster  expected_age_public_key  (from that repo's .sops.yaml at collection time)"
} > "$MANIFEST"

TOTAL=0
for C in "${CLUSTERS[@]}"; do
  NAME="$(basename "$C")"
  [[ -d "$C" ]] || { log "SKIP $NAME — not a directory"; continue; }
  mkdir -p "$ROOT/$NAME"
  n=0
  for f in "${SECRET_FILES[@]}"; do
    [[ -f "$C/$f" ]] || continue
    cp -p "$C/$f" "$ROOT/$NAME/$f" || die "copy failed: $NAME/$f"
    n=$((n+1))
  done
  for d in "${SECRET_DIRS[@]}"; do
    [[ -d "$C/$d" ]] || continue
    mkdir -p "$ROOT/$NAME/$d"
    find "$C/$d" -maxdepth 1 -type f ! -name '.DS_Store' -exec cp -p {} "$ROOT/$NAME/$d/" \; \
      || die "copy failed: $NAME/$d"
    n=$((n + $(find "$ROOT/$NAME/$d" -type f | wc -l | tr -d ' ')))
  done

  # The expected public key, captured now. Verification later compares the key
  # derived from the *restored* age.key against this. Empty is recorded as
  # empty and is treated as "cannot verify" downstream, never as a match.
  PUB="$(grep -oE 'age1[a-z0-9]{58}' "$C/.sops.yaml" 2>/dev/null | head -1)"
  printf '%s %s\n' "$NAME" "${PUB:-NONE}" >> "$MANIFEST"

  printf '  %-18s %2d files  sops-key %s\n' "$NAME" "$n" "${PUB:0:12}${PUB:+…}"
  TOTAL=$((TOTAL+n))
done
log "collected $TOTAL files from ${#CLUSTERS[@]} clusters"

if [[ $DRY_RUN -eq 1 ]]; then
  log "--dry-run: stopping before encryption. Nothing was written outside $STAGE."
  exit 0
fi

# ── Encrypt ──────────────────────────────────────────────────────────────────
TAR="$STAGE/fleet-escrow-$STAMP.tar.gz"
tar -czf "$TAR" -C "$STAGE" "fleet-escrow-$STAMP" || die "archive failed"
log "archive $(wc -c < "$TAR" | tr -d ' ') bytes"

ENC="$TAR.age"
echo
echo "Passphrase for this archive. It is the only thing that opens it — put it in"
echo "your password manager now, not afterwards. It must not go into MinIO, into"
echo "any repo, or into cluster.yaml."
echo
age -p -o "$ENC" "$TAR" || die "age refused to encrypt; nothing uploaded"
rm -f "$TAR"
[[ -s "$ENC" ]] || die "encrypted archive is empty"
log "encrypted $(wc -c < "$ENC" | tr -d ' ') bytes"

# ── Upload ───────────────────────────────────────────────────────────────────
[[ -f "$ENV_FILE" ]] || die "no credentials at $ENV_FILE (see age-key-escrow.md)"
PERM="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE" 2>/dev/null)"
[[ "$PERM" == "600" ]] || die "$ENV_FILE is mode $PERM; must be 600"
# shellcheck disable=SC1090
. "$ENV_FILE"
: "${MINIO_ENDPOINT:?not set in $ENV_FILE}"
: "${MINIO_BUCKET:?not set in $ENV_FILE}"
: "${MINIO_ACCESS_KEY_ID:?not set in $ENV_FILE}"
: "${MINIO_SECRET_ACCESS_KEY:?not set in $ENV_FILE}"

KEY="escrow/fleet-escrow-$STAMP.tar.gz.age"
SIG=(--aws-sigv4 "aws:amz:auto:s3" --user "$MINIO_ACCESS_KEY_ID:$MINIO_SECRET_ACCESS_KEY")

CODE="$(curl -sS --max-time 300 "${SIG[@]}" -o /dev/null -w '%{http_code}' \
  -X PUT --upload-file "$ENC" "$MINIO_ENDPOINT/$MINIO_BUCKET/$KEY")"
[[ "$CODE" == "200" ]] || die "upload returned HTTP $CODE"
log "uploaded s3://$MINIO_BUCKET/$KEY"

# ── Verify the uploaded copy, not the local one ──────────────────────────────
BACK="$VERIFY/readback.tar.gz.age"
CODE="$(curl -sS --max-time 300 "${SIG[@]}" -o "$BACK" -w '%{http_code}' \
  "$MINIO_ENDPOINT/$MINIO_BUCKET/$KEY")"
[[ "$CODE" == "200" ]] || die "read-back returned HTTP $CODE — the object is up but unreadable"

if ! cmp -s "$ENC" "$BACK"; then
  die "read-back differs from what was uploaded ($(wc -c < "$ENC" | tr -d ' ') vs $(wc -c < "$BACK" | tr -d ' ') bytes)"
fi
log "read-back is byte-identical"

echo
echo "Same passphrase again — this decrypts the copy that came back from MinIO."
echo
age -d -o "$VERIFY/readback.tar.gz" "$BACK" || die "the uploaded archive does not decrypt"
tar -xzf "$VERIFY/readback.tar.gz" -C "$VERIFY" || die "the uploaded archive does not extract"
EXTRACTED="$VERIFY/fleet-escrow-$STAMP"

echo
echo "Verification — age-keygen -y on each RESTORED key vs that repo's .sops.yaml:"
PASS=0; FAIL=0; UNKNOWN=0
while read -r NAME EXPECT; do
  [[ "$NAME" =~ ^# ]] && continue
  [[ -z "${NAME:-}" ]] && continue
  KEYFILE="$EXTRACTED/$NAME/age.key"
  if [[ ! -f "$KEYFILE" ]]; then
    printf '  %-18s COULD NOT TELL — no age.key in the restored archive\n' "$NAME"
    UNKNOWN=$((UNKNOWN+1)); continue
  fi
  GOT="$(age-keygen -y "$KEYFILE" 2>/dev/null)"
  # Both sides must be non-empty. Two empty strings compare equal, and that is
  # how a check that measured nothing reports success.
  if [[ -z "$GOT" || "$EXPECT" == "NONE" || -z "$EXPECT" ]]; then
    printf '  %-18s COULD NOT TELL — derived=%s expected=%s\n' \
      "$NAME" "${GOT:+ok}${GOT:-empty}" "${EXPECT:-empty}"
    UNKNOWN=$((UNKNOWN+1))
  elif [[ "$GOT" == "$EXPECT" ]]; then
    printf '  %-18s PASS\n' "$NAME"
    PASS=$((PASS+1))
  else
    printf '  %-18s FAIL — restored key derives %s, .sops.yaml says %s\n' \
      "$NAME" "${GOT:0:16}…" "${EXPECT:0:16}…"
    FAIL=$((FAIL+1))
  fi
done < "$MANIFEST"

echo
log "verified: $PASS pass, $FAIL fail, $UNKNOWN could-not-tell"
echo "  object: s3://$MINIO_BUCKET/$KEY"

# Three outcomes, not two. "Could not tell" is not a pass, and exiting 0 on it
# is exactly how an unverifiable escrow comes to be recorded as verified.
if [[ $FAIL -gt 0 ]]; then exit 1; fi
if [[ $UNKNOWN -gt 0 ]]; then exit 2; fi
echo
echo "Every restored key matches its repo. age_key_escrowed: true is now a"
echo "statement with evidence behind it for these clusters."
exit 0

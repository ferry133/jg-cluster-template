# Provision one customer cluster

One delivery, start to handover. Every step has a precondition, a command, an
**assertion**, and a **failure branch**. Work top to bottom; do not skip a step
because the one after it appears to have worked.

## Read this before step 1

**A check is a thing that needs verifying, whichever way it points.** This
runbook is made almost entirely of checks executed by a person, and on
2026-08-17 a single day of work on §2 produced six cases where the check, not
the artifact, was the defect — in both directions:

- `makejinja --version` printed `1.9.8` while makejinja `2.8.2` was correctly
  installed. Click's `version_option(None)` had resolved to rich-click. **Green
  and false.**
- A full-length `AGE-SECRET-KEY-1` string was found inside the factory image's
  `/usr/local/bin/age-keygen`. The binary is checksum-identical to upstream age
  v1.3.1, so that string is in every copy anyone has ever downloaded. **Red and
  false.**

So, three rules that apply to every step below:

1. **Prefer asserting against a checksum, a digest, or distribution metadata
   over reading a tool's self-report.** A version a tool prints about itself is
   the least trustworthy number available.
2. **Before believing a negative, prove you asked the right thing.** `NotFound`,
   "no output", "no events" and "cannot connect" are produced both by the
   healthy case and by asking the wrong cluster, the wrong account, or a
   component that died. Every assertion below that reads an absence carries a
   **positive control** — something that *must* be present in the same breath.
3. **Write down what you compared, not what you concluded.** "escrowed" is a
   conclusion. "compared, public halves match verbatim" is what was done.

**This page is in a public repository, by decision.** An accurate procedure with
no credentials in it is what is meant to be public, so nothing here is softened
for that reason. What it does mean: never paste a real token, password, customer
address or `cluster.yaml` excerpt into this file or into any issue that quotes
it — see the `cluster.yaml` rule in step 3, which is the one place an operator
is most likely to do it by reflex.

## What the customer does, and what you do

The customer performs **three physical actions** (network cable, power, power
button — `README-zero-IT.md`) and, **at contract time and before shipping**,
registers **one Google account** representing this cluster (D11). Everything
else on this page is yours.

That Google account is the spine of the whole delivery: Cloudflare and Auth0 are
registered by the company *using the customer's account*, so at end of service
the customer changes one password and the external services are theirs.

> ⚠️ **The central claim of that model is untested** (D11). Changing the
> password blocks obtaining *new* credentials; it does not revoke *already
> issued* ones. Cloudflare API tokens and the Auth0 client secret are
> independent bearer credentials whose validity does not depend on how the
> account is logged into. Nobody has measured whether a Cloudflare API token
> survives a password change. **Do not tell a customer that changing the
> password revokes company access** until that is measured — say that the
> account becomes theirs and that outstanding tokens are revoked separately
> (§6.4's revocation list).

---

## Step 0 — Escrow `age.key`, and prove the copy is the key

**This step is out of order on purpose.** It appears first because it is the one
step with no second chance and no automated backstop: 1.5 closed with factory
never touching escrow, so this record is the *entire* verification that customer
backups are recoverable. Perform it as soon as `age.key` exists (after Stage 3
of `docs/deploy/manual.md`) and before anything else depends on it.

Full policy — what to escrow, where, and why the repo does not need it:
`docs/operations/age-key-escrow.md`. Not repeated here.

**Precondition:** `age.key` exists in the cluster directory and `.sops.yaml` has
been generated.

```sh
# 1. Copy the key to the escrow store (password manager entry on the operator's
#    account, or an encrypted archive independent of the R2 bucket).
#    NOT the same R2 bucket as the backups.

# 2. Read the public half back OUT OF THE ESCROWED COPY — not out of the cluster.
age-keygen -y /path/to/escrowed-age.key

# 3. Read the recipient the cluster actually encrypts to.
grep -A1 'age:' .sops.yaml
```

**Assertion:** the two public keys are **byte-identical**. Compare them
character by character, or:

```sh
[ "$(age-keygen -y /path/to/escrowed-age.key)" = "$(grep -oE 'age1[a-z0-9]+' .sops.yaml | head -1)" ] \
  && echo "MATCH" || echo "MISMATCH — do not proceed"
```

**Why this and not a file check:** a truncated copy reads exactly like a good
one (`docs/operations/age-key-escrow.md:36-50`). Size, name and presence all
look right on a key that cannot decrypt anything. The public half is the only
thing that identifies the material.

**Record this, in these words:**

```
age.key escrow — <cluster_name>, <date>, <who>
  escrow location: <password manager entry / archive path>
  age-keygen -y on the escrowed copy: age1<...>
  .sops.yaml age: recipient:            age1<...>
  compared: public halves match verbatim
```

**Do not write "escrowed".** `jgt-appliance` declares `age_key_escrowed: true`
today on the strength of that weaker word, and no one has ever checked it. That
is the failure already in the field, not a hypothetical. Only after the record
above exists may you set:

```yaml
# cluster.yaml
age_key_escrowed: true
```

**Failure branch — public halves differ:** the escrowed copy is not this key.
Delete it from the escrow store (a wrong key in an escrow slot is worse than an
empty slot — it will be trusted), re-copy, and repeat from step 2. Do not set
`age_key_escrowed: true`. Validation will refuse to render the appliance, which
is the intended outcome.

**Failure branch — `.sops.yaml` has no `age:` line:** you are ahead of Stage 3.
Escrow nothing yet; the key may still be regenerated.

**Handover consequence:** handing the cluster over means handing over `age.key`.
From that moment the operator's escrowed copy is a second key to someone else's
data. Either destroy it and record that, or tell the customer plainly that it
still exists.

---

## Step 1 — The customer's Google account

**Precondition:** the customer registered it at contract time. You have the
address and password.

**Assertion:** log in at `accounts.google.com` and confirm the account is
reachable *and that 2FA is either off or its second factor is available to
you* — a Google account with 2FA bound to the customer's phone will block every
later step at an unpredictable moment, usually the Cloudflare signup.

**Failure branch — 2FA bound to a device you do not have:** stop. This is not
worked around; every downstream registration needs this login. Get the customer
to either disable it for the delivery window or provide the second factor.
Record which was done, because it affects handover.

**Failure branch — account does not exist:** stop and escalate. Do not create
one on the customer's behalf: D11's entire premise is that the account is the
customer's own, and one you created is one you own.

---

## Step 2 — Domain, Cloudflare, Auth0 — all under that account

Per D11 option **B**: the customer's own domain, NS-delegated to the Cloudflare
account registered under their Google account. The hostname is final from day
one, so handover is an NS change and nothing the customer uses has to be
reconfigured.

Mechanics — token scopes, tunnel creation, the exact dashboard fields — are
**Stage 4 of `docs/deploy/manual.md`**. Not repeated here. What this runbook
adds is what to assert afterwards.

**Assertion — the Cloudflare token points at the zone you think it does.** Do
not stop at `/user/tokens/verify`; it returns "valid and active" for a token
belonging to an entirely different account.

```sh
# The zone's nameservers, per Cloudflare
curl -sS -H "Authorization: Bearer $CF_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=$DOMAIN" \
  | jq -r '.result[] | "\(.name) \(.status) \(.name_servers|sort|join(","))"'

# The live delegation, per public DNS — two independent resolvers
curl -sS -H 'accept: application/dns-json' \
  "https://cloudflare-dns.com/dns-query?name=$DOMAIN&type=NS" | jq -r '.Answer[].data'
curl -sS "https://dns.google/resolve?name=$DOMAIN&type=NS" | jq -r '.Answer[].data'
```

The Cloudflare `name_servers` set must **equal** the live delegation set, and
`status` must be `active`. Measured failures this catches, both of which pass
every cheaper check:

- **A same-named zone in an abandoned account.** `status: moved`, nameservers
  `carioca`/`luke` while the domain is really delegated to `marge`/`sage`. The
  stale zone held eight complete, correct-looking records for hostnames that are
  NXDOMAIN worldwide.
- **The wrong token entirely.** `GET /zones` returned
  `{"success":true,"errors":[],"result":[]}` under **HTTP 200** — not a 403, a
  well-formed empty answer — because an R2 access key had been pasted into the
  DNS token field. external-dns then filters against an empty zone list, skips
  every record, and logs **nothing at all** at info level. Hours of zero log
  lines is what healthy looks like.

**Do not run these checks with `dig` from an appliance LAN, and naming a server
does not save you.** Any host whose queries traverse the appliance gateway is
affected: the gateway transparently redirects all outbound UDP/53, so
`dig @1.1.1.1` is answered by the cluster, and `dig @192.0.2.1` — unroutable by
definition — answers too. DoH over 443 is immune, which is why the commands
above are `curl`, not `dig`. This is not split-horizon resolution; that was the
first guess and it was wrong.

**Assertion — Auth0.** Registered under the same Google account. Per instance,
in the Regular Web Application:

```
Allowed Callback URLs:            https://<instance>.<domain>/oauth2/callback
Allowed Logout URLs / Web Origins: https://<instance>.<domain>
```

A wildcard `https://*.<domain>/oauth2/callback` covers the whole customer domain
at once. `task configure` prints the exact URLs it expects — compare against
that output rather than typing from memory.

**Failure branch — callback URL missing or misspelled:** login fails with an
Auth0 error and **there is no fallback**. In OIDC mode ttyd binds loopback only
and oauth2-proxy is the sole route in. Symptom is indistinguishable from a
broken deployment. Fix the URL in Auth0; no redeploy is needed.

---

## Step 3 — Cluster, repo, render, bootstrap

Mechanics: **Stages 1–3 and 5–7 of `docs/deploy/manual.md`**, path (B) Omni
unless this delivery is an explicit manual-Talos exception. Not repeated here.

Three assertions this runbook adds:

### `cluster.yaml` is never committed. Not once, not "temporarily".

It holds plaintext credentials — the Cloudflare token, the R2 keys, and a
**fleet-wide** Auth0 client secret shared by every cluster. It is gitignored
(`.gitignore:19`) and has never been committed in any cluster repo.

**These repos are public by decision** — `jg-cluster-template`, `jg-base`,
`k8scc`, `jgt-appliance`, `jg-jiahd` and `jcom`. In a public repo one stray
`git add` is permanent: it is in every fork and every clone before anyone
notices, and the exposed Auth0 secret is not this customer's, it is the whole
fleet's. There is no cleanup that undoes it — only rotation across every
cluster.

What *is* committed is the **rendered output**: `kubernetes/`, with secrets
SOPS-encrypted to the cluster's age recipient.

**Assertion — it is still ignored and still absent from history:**

```sh
git check-ignore -v cluster.yaml         # must print the .gitignore rule
git log --all --oneline -- cluster.yaml  # must print NOTHING
git status --short                       # cluster.yaml must not appear
```

The middle command is `--all` on purpose. "Genuinely never committed" and
"nobody ever checked" produce the same empty output from a lazier command, and
only one of them is safe.

**Failure branch — `git log --all` prints anything at all:** stop the delivery.
The credential is public and already cloned. Rotate the Auth0 client secret
fleet-wide, the Cloudflare token, and the R2 keys, before doing anything about
the repository. Removing the file or rewriting history does not un-publish it.

**Assertion — the render happened against the values you just set.** Re-run
`task configure --yes` and confirm the tree is clean afterwards; a dirty tree
means a previous render is what is deployed, not the current `cluster.yaml`.

**Assertion — Flux has fetched the commit, before you interpret anything as
absent.**

```sh
kubectl get gitrepository -A \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,REV:.status.artifact.revision'
```

`READY=True` **and** the revision equal to the SHA you pushed. Until both hold,
every "not deployed yet" observation is unreadable.

**Failure branch — cloudflared CrashLoopBackOff with QUIC handshake timeouts:**
the node's egress blocks UDP 7844 while TCP 443 works. Not a token problem;
rotating the token does not help. Apply the `TUNNEL_TRANSPORT_PROTOCOL: http2`
patch — see the Troubleshooting section of this repo's `CLAUDE.md` for the exact
patch and where it goes.

---

## Step 4 — Pin the LAN address, then point the router's DNS at it

Full detail, including the three router approaches and which to prefer:
`docs/operations/router-dns.md`. Not repeated here. **Order matters and this
runbook enforces it.**

**Pin first.** On an appliance the addresses come from ARP probing, which
re-checks on every pass and may reselect. An address written into a router is an
external contract; a reselection leaves the router pointing at nothing and every
internal name fails at once **with nothing in the cluster looking wrong**.

```sh
kubectl -n network get svc k8s-gateway \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'
```

Write that into `cluster.yaml` as `lan_shared_addr`, re-render, push. The probe
finds **two** addresses — read the shared one off the running service with the
command above; do not assume it is the first or the higher.

**Then set the router's DNS**, default approach DHCP-DNS-server-plus-secondary
(the only one every router has). Always set a secondary.

**Assertion — from a LAN client, a laptop on Wi-Fi, not the node:**

```sh
nslookup internal.<domain>      # must return the pinned address
nslookup github.com             # positive control: forwarding still works
```

The second line is the positive control. Without it, a cluster that answers
*everything* with NXDOMAIN looks like a working configuration for the one name
you happened to test.

**Failure branch — returns nothing:** the DHCP lease has not renewed. Reconnect
the client and retry **before changing anything**.

**Known limit, tell the customer:** a secondary DNS covers the cluster going
*silent*. It does not cover the cluster answering *wrongly* — a client accepts
an NXDOMAIN or SERVFAIL and never asks the secondary. A router reset, a
replacement unit or an ISP-pushed config all silently undo this step; the daily
health check reports `LAN cannot resolve internal names` as a FAIL and withholds
the dead-man ping.

---

## Step 5 — Before you call it delivered

- [ ] Step 0's escrow record exists and says **"compared, public halves match
      verbatim"**. `age_key_escrowed: true` is set only because that record
      exists.
- [ ] Cloudflare zone `name_servers` **equal** the live delegation, measured via
      DoH from a host **not** behind the appliance gateway.
- [ ] Auth0 callback URLs registered for every instance in `claude_instances`.
- [ ] `cluster.yaml` **not** committed — `git log --all -- cluster.yaml` empty,
      `git check-ignore` prints the rule. The rendered `kubernetes/` tree is
      what was pushed, working tree clean.
- [ ] GitRepository `READY=True` at the pushed SHA.
- [ ] `lan_shared_addr` pinned in `cluster.yaml` *before* the router was touched.
- [ ] `nslookup internal.<domain>` **and** `nslookup github.com` both correct
      from a LAN client.
- [ ] Daily health check configured (`daily_check_*`) — otherwise the CronJob
      prints "not configured", exits 0, and the cluster has no health check while
      showing no failures.
- [ ] Revocation list for this delivery recorded (§6.4), naming every credential
      issued and how it is revoked. Password change alone does not revoke
      already-issued tokens.

---

## When a step fails in a way this page does not describe

**Stop and escalate with evidence. Do not retry indefinitely.** Record what you
ran, what you expected, and what you got verbatim — including output that looked
like nothing, because "no output" is a finding and not the absence of one.

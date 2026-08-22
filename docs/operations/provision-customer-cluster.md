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

## Run the checks, do not eyeball them

`scripts/delivery-check.py` executes the assertions on this page. Prefer it over
reading command output by eye — not because the commands are hard, but because
the judgement each one needs is the part that decays under time pressure.

```sh
scripts/delivery-check.py escrow       --escrowed-key /path/to/escrowed-age.key
scripts/delivery-check.py repo-hygiene --dir . [--deep]
scripts/delivery-check.py dns          --domain <domain>   # $CLOUDFLARE_TOKEN
scripts/delivery-check.py flux         --kubeconfig kubeconfig --expect-sha <sha>
scripts/delivery-check.py lan          --domain <domain> --expect-addr <addr>
```

**It has three exit codes, and the third is the point.** `0` pass, `1` fail,
**`2` could not tell** — a missing tool, an unreachable resolver, an absent
token. With only two codes, "I could not measure this" has to be squeezed into
one of them, and it always gets squeezed into the green one. **Treat `2` as
unfinished work, not as a pass with a caveat.**

The prose below stays because it explains *why* each assertion is shaped the
way it is, and because a step the script cannot run — Auth0 callback URLs, the
Google account, the escrow store itself — still has to be done by hand.

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

## Step −1 — Prepare the machine before the box ships

**This happens at the factory, on your bench, before anything in Step 1 needs to
exist.** It can run in parallel with Steps 1–2 (the customer's account and
domain); nothing here depends on them.

The goal is one state, and all six parts of it matter:

```
內碟有 omni-talos ／ 箱內無 USB ／ 從內碟開機 ／ maintenance mode
／ 插電自行註冊回 office Omni ／ 不再依賴 join token
```

Verified end to end on hardware 2026-08-22 (`zero-it-onboarding` D14). The USB is
a **factory tool and is not shipped** — an appliance customer is never asked to
select a boot device.

### 1. Boot the Omni ISO from USB

**Assertion** — the machine appears in Omni, and you are looking at the right one:

```sh
omnictl get machinestatus <uuid> -o json     # maintenance: true, no `installed` label
omnictl get disks -n <uuid>                  # positive control: Omni can reach it
```

The disk listing is the positive control. Without it, "no `installed` label" is
produced equally by a machine with an empty disk and by reading the wrong
machine.

**The Talos API is not reachable on the LAN.** Measured: ports `50000`/`50001`
refused at the machine's LAN address; an Omni-ISO machine exposes the API only
over SideroLink. Everything here goes through Omni, addressed by **machine
UUID**, never by IP — and that is not a workaround, it is the only thing that
works once customer LANs overlap (`deployment-profiles` D49).

### 2. Create a throwaway cluster that names the install disk

```yaml
kind: Machine
name: <uuid>
patches:
  - idOverride: 100-<cluster>-install-disk
    inline: |
      machine:
        install:
          disk: /dev/nvme0n1        # ← read it, do not assume it
```

> ⚠️ **Naming the disk is the one line that cannot be skipped.** The boot USB is
> itself a disk. Measured on the test machine: `/dev/sda`, 31 GB, `USB DISK 3.0`
> next to `/dev/nvme0n1`, 256 GB, `Kingchuxing`. Letting Omni choose can install
> to the USB, **and the whole run looks like a success until the stick is pulled.**
> Read model, size and transport before writing the patch.

**Assertion** — after the install completes:

```
installed = True          systemdisk = the disk you named
```

**Failure branch — `systemdisk` is the USB:** stop. The machine must be
re-imaged; nothing later in this runbook detects it.

### 3. Delete the cluster

**Assertion — both halves, and the pair is the point:**

```
installed   = True     ← the system survived on disk
maintenance = True     ← the config is gone
```

Omni resets only the STATE and EPHEMERAL partitions, so the OS stays. Also check
the machine's node unique token:

```sh
omnictl get nodeuniquetokenstatus <uuid> -o json     # state 1 = PERSISTENT
```

`PERSISTENT` is what makes the shipped machine independent of the join token —
it is granted because Talos is *installed*, not because it is in a cluster.

**Failure branch — `installed = False`:** the reset took the system with it. Go
back to step 2; do not ship a machine in this state, it will boot to nothing.

### 4. Remove the USB, power off, ship

**Assertion** — the USB is gone from the machine's own view, not just from the
bench:

```sh
omnictl get machinestatus <uuid> -o json     # exactly one disk, flagged system
```

**Then shut down** with `omnictl machine shutdown <uuid>`, and **verify by ping,
not by Omni**. Measured: `connected` still read `true` for more than two minutes
after the machine stopped answering. Omni's connection state lags reality, and a
stale `true` reads exactly like a healthy machine.

### 5. On arrival — the assertion that proves the whole design

Plug in power and network, press the button. Then:

| | expected |
|---|---|
| `machinestatus` **version** | **increases** — this is how you know it really came back |
| address | **different** from the factory's |
| `installed` / `maintenance` | True / True, unchanged |
| node unique token | `PERSISTENT`, unchanged |
| join token **usecount** | **unchanged** |

**The last row is the one that matters.** An unchanged usecount proves the
machine came back on its own identity and never spent the join token — which is
why the token's job is provenance, not lifetime, and why it must not expire
(`zero-it-onboarding` D13).

Use **version**, not `connected`, to decide it is back: see the lag above.

**Failure branch — the machine never appears:** five different faults produce
this identical observation — no power, no boot, no DHCP, outbound blocked,
firmware not booting the internal disk (`zero-it-onboarding` D8). Do not report
"machine did not appear" as a diagnosis; it is one symptom of five causes.

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
(`.gitignore:19`).

**This has already gone wrong, repeatedly, so do not read the rule as
precautionary.** Measured 2026-08-17 by running the content scan below:
`config.gen/cluster.yaml` was committed in **jcom** and **jg-jiahd**, both
public. jcom holds three versions of the file, two carrying a plaintext
`cloudflare_token`; jg-jiahd holds **11 token-bearing copies across 8 distinct
token values**. Both were untracked in April 2026 — jcom at `afb510f`, jg-jiahd
at `e6803aa`, both titled *"chore: untrack sensitive config files"* — and **the
blobs are still reachable**. Untracking removed the file from the tip and
published it forever.

Note the shape, because it is the one to guard against and it is not a simple
oversight: the ignore rule named `/cluster.yaml`, and the file that leaked was
at `config.gen/cluster.yaml`. **A path-specific rule and a path-specific check
both pass while the same content sits one directory over.** The control and the
verification failed identically because they shared a premise, not because
either was implemented badly — two safeguards resting on one assumption are one
safeguard.

> **Incident record lives elsewhere.** These figures are here as the worked
> example behind the method, and they are deliberately not the tracking record
> for the exposure. As of 2026-08-17 it is **deferred, not remediated** — no
> rotation, no liveness testing — by ferry133's decision, and `jcom` and
> `jg-jiahd` own it, not this repository.

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
# FIRST: is the rule in the repository, or only on this machine?
git ls-files --error-unmatch .gitignore     # must succeed — .gitignore is tracked
git show HEAD:.gitignore | grep cluster.yaml  # must print the rule

git check-ignore -v cluster.yaml            # then: does it apply here
git status --short                          # cluster.yaml must not appear

# Any path, not just this one — see the config.gen/ case above.
git log --all --oneline -- '*cluster.yaml'  # must print NOTHING

# And by content, since the next leak will be at a filename nobody predicted.
git rev-list --all --objects \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(rest)' \
  | awk '$1=="blob"{print $2, $3}' \
  | while read -r sha path; do
      git cat-file blob "$sha" 2>/dev/null \
        | grep -qE '^(cloudflare_token|claudecode_auth0_client_secret|backup_r2_secret_access_key):[[:space:]]*[^"'"'"' ]' \
        && echo "CREDENTIAL IN HISTORY: $path ($sha)"
    done | sort -u
```

`--all` and `'*cluster.yaml'` are both deliberate. "Genuinely never committed"
and "nobody ever checked" produce the same empty output from a lazier command,
and only one of them is safe — and a check pinned to one path is a lazier
command, which is exactly how `config.gen/cluster.yaml` stayed invisible.

**The first two lines are the ones that would have caught jg-jiahd, and the
version of this check without them would not have.** Measured 2026-08-17:
jg-jiahd has **no `.gitignore` in `HEAD` at all**. `git check-ignore` there
reports `.gitignore:18` and looks perfectly healthy, because the file exists on
that workstation and is untracked — `~/.gitignore_global` ignores `.gitignore`
itself, so it never shows in `git status`, never lands via `git add`, and
closing the path needs `git add -f`. A fresh clone of jg-jiahd has no rule for
`cluster.yaml` or `config.gen/cluster.yaml` whatsoever. That is why eleven
copies landed there and two in jcom.

Take the general form, because it is the sharpest version of the shared-premise
problem on this page: **`git check-ignore` measures the machine you are standing
on, and that is also the machine doing the verifying.** The control and the
check are not merely correlated — the control exists *only* in the one place
that would ever test it. Every clone that matters, a colleague's, CI's, a
rebuilt workstation, has neither. **A protection that lives outside the thing it
protects is not a protection; it is a local habit that reports as one.**

Consequence for the failure branch below: on a repo in this state, "close the
path" is `git add -f .gitignore` and a commit, not an edit to the file. Rotating
first there produces the next published copy.

The content scan is slow on a large history. Run it once per repo, not per
delivery.

**Consequence nothing in the commit tells you: these commits are not
self-contained.** Because `cluster.yaml` never enters git, the `extras:` line
that selects an app, and every value you typed, exist only on the machine that
rendered. A fresh clone re-rendering **drops them** unless that machine's
`cluster.yaml` carries the same content. The commit shows the rendered result
and says nothing about the input that produced it.

So the escrow copy of `cluster.yaml` (step 0) is not belt-and-braces — it is the
only copy of the cluster's inputs that survives the machine. If you provision
from a second workstation, copy `cluster.yaml` across first and confirm it
renders to the same tree before pushing.

**Failure branch — either check prints anything at all:** stop the delivery.
The credential is public and already cloned. Then, in this order:

1. **Close the path first.** Fix the ignore rule and confirm the file is no
   longer reachable by *any* path — the glob above, not the one you expected.
   This takes seconds and it has to come first, for the reason in the next
   paragraph.
2. **Then rotate** the Cloudflare token, the fleet-wide Auth0 client secret,
   and the R2 keys.
3. **Then re-run both checks** against the new credential, before the next
   commit.

**Rotating before closing the path publishes the new token too.** That is not a
hypothetical: jg-jiahd's history holds **11 copies of `config.gen/cluster.yaml`
carrying a `cloudflare_token`, spanning 8 distinct token values** between
2026-03-04 and 2026-04-12. Each rotation produced a new secret and committed it
down the same open path — a remediation loop that felt like progress and
published one more credential every time round. Enumerated 2026-08-17; jcom has
2 more, and one value appears in four repositories across two domains, so
"rotate the affected cluster's token" can also be scoped too narrowly.

**And untracking is not remediation.** `chore: untrack sensitive config files`
reads like a fix and is not: it stops the next clone from seeing the file at the
tip and leaves every existing clone, fork and cached view holding the token.
**Only invalidating the credential reduces exposure** — but do step 1 first, or
you are just adding to the series.

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
replacement unit or an ISP-pushed config all silently undo this step.

The daily health check catches it by resolving `internal.<domain>` through the
node's ordinary resolution path — the same path a client uses — and does not
care which of the three router methods is in force (D48). **It runs only where
the node's resolvers are the LAN's**, derived from `node_dns_servers`: unset
means yes. Pin those to a public resolver and the row disappears rather than
alarming daily, which is a real blind spot on such a cluster.

---

## Step 5 — Before you call it delivered

- [ ] The machine arrived **on its own identity**: the join token's `usecount`
      is unchanged since Step −1, and its node unique token is `PERSISTENT`.
      An increased usecount means it re-registered as a new machine — the disk
      was not carrying what you shipped.
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

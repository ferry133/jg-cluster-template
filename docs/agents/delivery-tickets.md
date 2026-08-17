# Delivery tickets — the state machine for one customer delivery

One GitHub issue tracks one customer delivery, from contract to handover.
Enforced by `scripts/delivery-ticket.py`; this file is the vocabulary and the
reasoning. §3 of the `factory-agent` change.

**The ticket is the durable record.** factory restarts, sessions end, and
deliveries change hands part-way. Anything not written to the ticket did not
happen — not as a slogan, but because there is no other place that survives all
three.

## Phases

Ordered. Exactly one phase label on a ticket at any time.

| | phase | means |
|---|---|---|
| 0 | `delivery/intake` | ticket opened; customer, profile and expected machines recorded |
| 1 | `delivery/awaiting-hardware` | shipped; waiting for the machine to reach Omni |
| 2 | `delivery/provisioning` | cluster, repo, DNS and tunnel being built |
| 3 | `delivery/verifying` | the runbook's assertions are being run |
| 4 | `delivery/handover` | handover package produced and delivered |
| 5 | `delivery/done` | |

`delivery/blocked` is **not** a phase. It is added alongside the current phase
label, from anywhere, and removed on the next successful advance. It keeps the
phase so `resume` still knows where the delivery stopped — a blocked ticket that
lost its phase is a ticket someone has to reconstruct by reading comments.

### How this relates to `triage-labels.md`

They are different vocabularies for different objects and they do not mix.
`docs/agents/triage-labels.md` triages **incoming issues about this repo**:
`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix` —
questions about who should act on a report. Delivery phases track **the progress
of a unit of work that is already fully specified**. The `delivery/` prefix
exists so the two never collide in a label list or an autocomplete.

A delivery ticket may still carry a triage label when it needs a decision, and
that is the intended overlap: `delivery/blocked` says the delivery stopped,
`ready-for-human` says who unblocks it.

## What the script refuses, and why each refusal exists

Each of these is a guarantee an agent would otherwise have to remember. A rule
in prose is followed until the run where it matters.

**Two phase labels at once.** Not auto-repaired. Which label is correct is a
question about the world, not about the labels, and picking one writes a guess
down as fact.

**Skipping a phase** without `--force`. Skipping is how a delivery reaches
handover with verification never having run. `--force` exists, and an
unexplained `--force` is indistinguishable from a mistake to whoever resumes —
so it wants a comment saying why.

**A comment containing key material.** These repositories are public and editing
a comment does not unpublish it; the value would need rotating, not deleting.
Record an identifier or a fingerprint instead: *"token ending 4f21"*, *"recipient
age1u02z…"*. The scanner covers age keys, Cloudflare tokens, GitHub PATs, PEM
keys, JWTs, and the known credential fields of `cluster.yaml`.

It is deliberately quiet about `field: ""`, `"<your-token>"`, `"${CF_TOKEN}"`
and `CHANGE-ME`. Those are what correct documentation looks like, and the first
version of this scanner flagged all three — **a guard that fires on the examples
gets switched off, and a switched-off guard reads exactly like a passing one.**

**A recorded state that disagrees with an observed one.** `check` stops instead
of reconciling. "The ticket was advanced for work that did not finish" and "work
finished without being recorded" need opposite corrections, and they look
identical from the ticket alone.

## Resume

`resume` reports the phase, whether it is blocked, and which phases are behind
it. It reads labels, so it reports **what was claimed**, not what is true.

After a crash, re-run the current phase's assertions before advancing. The phase
most likely to be half-done is the one that was in progress, and it is the one
`resume` will tell you is not finished — which is correct but easy to read as
"nothing to check here".

## Usage

```sh
scripts/delivery-ticket.py phases
scripts/delivery-ticket.py create  --customer "Acme" --profile appliance --machines 1
scripts/delivery-ticket.py advance 42 --to delivery/provisioning
scripts/delivery-ticket.py comment 42 --file progress.md
scripts/delivery-ticket.py resume  42
scripts/delivery-ticket.py check   42 --observed delivery/verifying
```

`--repo owner/name` targets a repository other than the current directory's.

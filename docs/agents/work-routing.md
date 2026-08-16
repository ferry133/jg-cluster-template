# Work routing across repos

Which repo's agent owns a piece of work, when the work touches more than one.

## Why this needs a rule

Every project repo here has an agent working in it, and that agent accumulates
the history of what was designed, tried, and rejected. Any session can edit any
repo — but a session that edits a repo it does not belong to leaves the knowledge
somewhere the next person will not look.

The concrete failure: someone fixes a backup defect while working on cluster A.
Months later the same defect surfaces on cluster B, and the agent working there
has no way to discover that it was already solved. The fix is repeated, or worse,
solved differently.

This repo's own architecture guarantees the problem. Every extra app spans three
repos (`jg-base` + `jg-cluster-template` + the user repo), so "one repo per
change" is false most of the time. A tie-breaker is required, not optional.

## The rule

**The owner is the repo where the artifact changes** — in practice, the repo
whose files the change actually edits, and where the design decision lands.

Everything else is a collaborator and gets a linked pointer, never a second copy
of the work.

### Verification location is not ownership

The place a defect shows up, and the place it can be proven fixed, are often not
the repo that changes. Both are real contributions; neither confers ownership.

Worked example (2026-08-16): MariaDB databases had no backup path. The symptom
appeared on jcom — the only cluster running MariaDB, and therefore the only place
the fix can be verified. But the file that changes is
`jg-base/kubernetes/apps/base/monitoring/backup/app/configmap.yaml`, and no file
in jcom changes at all.

Routing it to jcom would have buried the history in the wrong place: the next
person to touch backup — adding another database, debugging an empty archive on
an appliance — is working in jg-base, and would find nothing.

So: **jg-base owns it, jcom holds the verification bed.**

## Linking is what actually fixes the scattering

Correct routing alone is not enough. If the thread cannot be found from the other
side, an agent working in the collaborating repo still hits the original problem.

- The **owning repo** gets the full issue: the defect, the constraints, the
  acceptance criteria.
- Each **collaborating repo** gets a short issue that states the owner up front
  (`Owner: <owner>/<repo>#N`) and holds only the facts that genuinely belong to
  it — the local data shape, what to run there, what is configured there.
- GitHub cross-repo references (`ferry133/jg-base#1`) work in both directions, so
  either agent can walk to the other.

A collaborator issue that restates the work is worse than none: two copies of a
procedure diverge, and the wrong one gets followed.

## openspec changes: the design record and the implementation can differ

A change that spans repos has two things to route, and they do not always land in
the same place.

- **The change itself** — proposal, design, specs — belongs to the repo that
  holds the specs it modifies. `jg-cluster-template` holds `openspec/specs/`, so
  changes amending those stay here even when most of the code lands elsewhere.
- **Each implementation work item** belongs to the repo whose files change, as an
  issue in that repo.

The MariaDB gap is the pattern in miniature: D46 and task 7.7 are design record
and stayed in `jg-cluster-template`'s openspec; the fix is an issue on
`jg-base`, where the file lives; `jcom` holds a pointer because it is the
verification bed.

`openspec/config.yaml` makes this a required field rather than a judgement call —
every proposal declares `**Owning repo**` and, when they differ,
`**Implementation lands in**`. The point of writing it down at proposal time is
that it stops being re-decided, differently, at the start of every work session.

### Root and sub-changes

When a repo's share of the work is large enough to need its own tasks, it gets a
**sub-change** in its own `openspec/` rather than a list of foreign tasks inside
the root. The root holds the plan; each sub-change holds the work and points
home.

Root proposal:

```markdown
**Sub-changes**：

| repo | change | 負責什麼 |
|------|--------|---------|
| `jg-base` | `backup-coverage` | dump 路徑與「沒涵蓋到」的表達 |
```

Sub-change proposal:

```markdown
Part of: `jg-cluster-template` / `deployment-profiles`
```

Rules that keep the two records from disagreeing:

- **The sub-change's author updates the root** when the sub-change is archived.
  Nobody else is watching it.
- **A root cannot be archived while any sub-change is still active.** Archiving
  it early strands work with no plan above it.
- **No copies.** A repo either owns a sub-change with its own tasks, or it holds
  nothing. There is no "keep a copy to read" — reading someone else's plan is
  what the link is for.
- **Not every cross-repo change needs this.** A one-line fix referenced from a
  task does not earn a sub-change; an issue in the owning repo is enough.
  Reach for a sub-change when that repo's share has its own tasks and its own
  acceptance.

### The links are prose, so something has to walk them

`openspec validate` cannot see past its own repo. `./scripts/check-change-orchestration.py`
walks both directions across the sibling repos and reports copies, dangling
parents, missing children, and roots archived ahead of their sub-changes.

It found the reason it exists on its first run: `jgt-appliance` and
`jgt-omni-accept` each carried five changes copied out of this repo when they
were generated, frozen on the day of the copy and never touched again. One still
described the off-site backup upload as "unverified for want of R2 credentials"
a day after it had been proven impossible for an entirely different reason, and
listed the restore drill as unstarted when it was three quarters done. Neither
repo owned a single task in them.

Run it before archiving a root, and when adding a sub-change.

## When ownership is genuinely ambiguous

Some changes edit two repos roughly equally — a new schema field in
`jg-cluster-template` plus its consumer in `jg-base`. Then:

1. Prefer the repo where the **decision** is recorded, not the one with more
   lines changed. A CUE constraint and an openspec design note outrank a
   mechanical edit.
2. Failing that, prefer the repo **furthest upstream** — the one others consume.
   Downstream repos can carry a pointer; upstream cannot easily discover
   downstream history.

## Agent memory is secondary

Memory gets pruned and does not survive a reset. The durable record is the repo:
commits, `openspec/`, issues. So the real value of routing work to a repo's agent
is that the agent **writes the record into the repo where the next person will
look** — memory should mostly hold pointers into that record.

Stated that way, the rule keeps working after any given agent's memory is gone.

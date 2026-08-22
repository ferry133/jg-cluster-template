# Work routing — this repo family

The general rule, the openspec root / sub-change format, and the link checker
live at user level in **`~/.claude/openspec-orchestration.md`**. They apply to
every project, not just this one, so they are not repeated here.

This page holds what is specific to the cluster family.

> **2026-08-22: the design records left this repo.** `openspec/` — five changes,
> the archive, and the four baseline specs — now lives in `ferry133/fleet-ops`
> (private). The reason is not an ownership reassessment; it is that this repo is
> public *and* a GitHub template, so every customer-named cluster repo created
> from it inherited a copy. **What did not change: implementation still belongs to
> the repo whose files change**, which for schema, templates and Taskfile is still
> this one. Read the proposal there, do the work here.

## Why the rule bites harder here than elsewhere

Most projects are one repo. This one is three, by design: every extra app spans
`jg-base` + `jg-cluster-template` + the per-cluster user repo. So "one repo per
change" is false most of the time, and the tie-breaker is load-bearing rather
than theoretical.

## Who owns what

| Repo | Holds | Typically owns |
|------|-------|----------------|
| `jg-base` | Kubernetes manifests every cluster consumes via Flux | Anything under `kubernetes/apps/` — controllers, jobs, RBAC, scripts in ConfigMaps |
| `jg-cluster-template` | CUE schema, Jinja2 templates, Taskfile | Schema fields, rendering, per-phase docs — the *implementation* of changes amending the template specs |
| `fleet-ops` (private) | `openspec/specs/`, every change amending them, routing decisions | The design record. Holds no implementation |
| user repo (`jg-jiahd`, `jcom`, `jgt-appliance`, …) | One `cluster.yaml`, its encrypted secrets, the Flux entry point | Only that cluster's own configuration |

`jg-base` is upstream of every cluster; `jg-cluster-template` is upstream of
every user repo. Neither consumes the other, so between those two the tie-break
is where the decision is recorded — which is `openspec/specs/`, and since
2026-08-22 that is `fleet-ops`. **The tie-break moved with it: it no longer
points at either of these two repos**, so for a change amending a template spec,
the proposal goes to `fleet-ops` and the implementation issue to whichever of
these repos owns the files.

**A user repo owns almost nothing.** It is where changes are *verified*, and
verification is not ownership. A cluster repo that starts accumulating shared
design is a signal something was routed wrong.

## Worked example: the MariaDB backup gap

2026-08-16. MariaDB databases had no backup path at all.

- The symptom appeared on **jcom** — the only cluster running MariaDB, and
  therefore the only place a fix can be proven to work.
- The file that changes is
  `jg-base/kubernetes/apps/base/monitoring/backup/app/configmap.yaml`. **No file
  in jcom changes.**

So `jg-base` owns it (issue ferry133/jg-base#1) and `jcom` holds a pointer
(ferry133/jcom#1) carrying only what is genuinely local: the data shape, the
credentials already present in that container, what to run there.

Routing it to jcom would have buried the history where nobody would look: the
next person to touch backup — adding a database, debugging an empty archive on an
appliance — is working in `jg-base`.

The design record went to neither. D46 and task 7.7 amend `deployment-profiles`'
specs, so they are wherever those specs are — since 2026-08-22, `fleet-ops`.
That split — design record in `fleet-ops`, implementation issue in `jg-base`,
pointer in the cluster repo — is the pattern to copy.

## Blast radius is not ownership either, but it changes the bar

A push to `jg-base` reaches every cluster within the hour, with no per-cluster
review in between. It still owns the change; it just means the acceptance
criteria have to include a cluster that does *not* have the thing being fixed.

## Declaring it

Every change declares `**Owning repo**` above `## Why`; the rule is in
`fleet-ops`' `openspec/config.yaml` so it is asked at proposal time. Note that
`Owning repo` now names where the *design record* lives, which is `fleet-ops` for
all of them — the line that decides who does the work is
`**Implementation lands in**`. Verify the links with:

```sh
~/.claude/scripts/check-change-orchestration.py
```

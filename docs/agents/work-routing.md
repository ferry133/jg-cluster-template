# Work routing — this repo family

The general rule, the openspec root / sub-change format, and the link checker
live at user level in **`~/.claude/openspec-orchestration.md`**. They apply to
every project, not just this one, so they are not repeated here.

This page holds what is specific to the cluster family.

## Why the rule bites harder here than elsewhere

Most projects are one repo. This one is three, by design: every extra app spans
`jg-base` + `jg-cluster-template` + the per-cluster user repo. So "one repo per
change" is false most of the time, and the tie-breaker is load-bearing rather
than theoretical.

## Who owns what

| Repo | Holds | Typically owns |
|------|-------|----------------|
| `jg-base` | Kubernetes manifests every cluster consumes via Flux | Anything under `kubernetes/apps/` — controllers, jobs, RBAC, scripts in ConfigMaps |
| `jg-cluster-template` | CUE schema, Jinja2 templates, Taskfile, `openspec/specs/` | Schema fields, rendering, per-phase docs, and every openspec change amending those specs |
| user repo (`jg-jiahd`, `jcom`, `jgt-appliance`, …) | One `cluster.yaml`, its encrypted secrets, the Flux entry point | Only that cluster's own configuration |

`jg-base` is upstream of every cluster; `jg-cluster-template` is upstream of
every user repo. Neither consumes the other, so between those two the tie-break
is where the decision is recorded — which is usually `openspec/specs/`, here.

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

The design record went to neither. D46 and task 7.7 are in this repo's
`openspec/`, because they amend `deployment-profiles`' specs, which live here.
That split — design record here, implementation issue in `jg-base`, pointer in
the cluster repo — is the pattern to copy.

## Blast radius is not ownership either, but it changes the bar

A push to `jg-base` reaches every cluster within the hour, with no per-cluster
review in between. It still owns the change; it just means the acceptance
criteria have to include a cluster that does *not* have the thing being fixed.

## Declaring it

Every change in this repo declares `**Owning repo**` above `## Why`; the rule is
in `openspec/config.yaml` so it is asked at proposal time. Verify the links with:

```sh
~/.claude/scripts/check-change-orchestration.py
```

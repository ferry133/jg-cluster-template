# jg-cluster-template

GitHub template repo for bootstrapping a new user cluster managed by ferry133.

Click **"Use this template"** to generate a private per-user repo, then follow the steps below.

## Architecture

This repo is the **tooling layer** for a three-repo system:

| Repo | Role |
|------|------|
| [`ferry133/jg-base`](https://github.com/ferry133/jg-base) | Golden Kubernetes manifests, watched by all clusters via Flux |
| `ferry133/jg-cluster-template` (this repo) | Tooling to bootstrap a new cluster |
| `user-X-cluster` (generated from this template) | Per-cluster secrets + Flux entry point |

## What `task configure` Produces

```
kubernetes/
  components/sops/
    cluster-secrets.sops.yaml   ← commit this to per-user repo
talos/                          ← gitignored; used by task bootstrap:talos
bootstrap/                      ← gitignored; used by task bootstrap:apps
.sops.yaml                      ← gitignored; generated per cluster
```

## Setup Steps

### 1. Install tools

```sh
mise trust && mise install
```

### 2. Configure

```sh
cp cluster.yaml.sample cluster.yaml
cp nodes.yaml.sample   nodes.yaml
# Fill in cluster.yaml and nodes.yaml
# Reference per-user-repo.sample.yaml for all available variables
task configure
```

### 3. Add Flux entry point

Create `flux/cluster/ks.yaml` using `per-user-repo.sample.yaml` as reference.
Uncomment the extras your cluster needs.

### 4. Commit and push

```sh
git add kubernetes/components/sops/cluster-secrets.sops.yaml
git add flux/cluster/ks.yaml cluster.yaml nodes.yaml
git commit -m "chore: initial cluster configuration"
git push
```

### 5. Bootstrap

```sh
task bootstrap:talos   # bootstrap Talos cluster
task bootstrap:apps    # install Flux and sync to git state
```

```sh
kubectl get pods --all-namespaces --watch
```

## Verification

```sh
flux check
flux get ks -A
flux get hr -A
```

```sh
task reconcile   # force Flux sync
```

## Maintenance

```sh
task talos:apply-node IP=<ip>     # apply config change to a node
task talos:upgrade-node IP=<ip>   # upgrade Talos on a node
task talos:upgrade-k8s            # upgrade Kubernetes version
task talos:reset                  # wipe cluster (DESTRUCTIVE)
```

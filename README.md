# jg-cluster-template

GitHub template repo for bootstrapping a new user cluster managed by ferry133.

Click **"Use this template"** to generate a private per-user repo, then follow the steps below.

## Architecture

This repo is the **tooling layer** for a three-repo system:

| Repo | Role |
|------|------|
| [`ferry133/jg-base`](https://github.com/ferry133/jg-base) | Golden Kubernetes manifests, watched by all clusters via Flux |
| `ferry133/jg-cluster-template` (this repo) | Tooling to configure and bootstrap a cluster |
| `user-X-cluster` (generated from this template) | Per-cluster secrets + Flux entry point |

## Prerequisites

- Kubernetes cluster already running and accessible
- `kubectl` works with the correct `kubeconfig` (place it at `kubeconfig` in repo root, or set `KUBECONFIG` env)
- Cloudflare account with domain and API token
- (Optional) NAS with NFS exports for `nfs-subdir` and `claude-code` extras

## What `task configure` Produces

```
kubernetes/
  components/sops/
    cluster-secrets.sops.yaml   ← commit this to per-user repo
bootstrap/                      ← gitignored; used by task bootstrap:apps
.sops.yaml                      ← gitignored; generated per cluster
```

## Cloudflare Configuration

### 1. Create API token

Go to Cloudflare dashboard → My Profile → API Tokens → Create Token.

- Use the **Edit zone DNS** template
- Name the token `kubernetes`
- Under **Permissions**, add `Zone - DNS - Edit` and `Account - Cloudflare Tunnel - Read`
- Limit to your specific account and zone, then create the token
- Save the token — you will need it in `cluster.yaml` as `cloudflare_token`

### 2. Create Cloudflare Tunnel

```sh
cloudflared tunnel login
cloudflared tunnel create --credentials-file cloudflare-tunnel.json kubernetes
```

This creates `cloudflare-tunnel.json` in the repo root (gitignored). The tunnel token inside is embedded into the cluster secrets by `task configure`.

## Setup Steps

### 1. Install tools

```sh
mise trust && mise install
```

### 2. Configure

```sh
cp cluster.yaml.sample cluster.yaml
# Fill in cluster.yaml
# Reference kubernetes/components/sops/cluster-secrets.sample.yaml in jg-base for all variable keys
task configure
```

### 3. Add Flux entry point

Create `flux/cluster/ks.yaml` using `per-user-repo.sample.yaml` as reference.
Uncomment the extras your cluster needs.

### 4. Commit and push

```sh
git add kubernetes/components/sops/cluster-secrets.sops.yaml
git add flux/cluster/ks.yaml cluster.yaml
git commit -m "chore: initial cluster configuration"
git push
```

### 5. Bootstrap Flux

```sh
task bootstrap:apps   # install Flux and sync to git state
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

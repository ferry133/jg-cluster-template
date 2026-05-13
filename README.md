# jg-cluster-template

GitHub template repo for bootstrapping a new user cluster managed by ferry133.

Click **"Use this template"** to generate a private per-user repo, then follow the steps below.

## Architecture

Three-repo system:

| Repo | Role |
|------|------|
| [`ferry133/jg-base`](https://github.com/ferry133/jg-base) | Golden Kubernetes manifests, watched by all clusters via Flux |
| `ferry133/jg-cluster-template` (this repo) | CUE schema, Jinja2 templates, Taskfile — tooling to configure and bootstrap |
| `user-X-cluster` (generated from this template) | Per-cluster secrets + Flux entry point only |

## Prerequisites

- Kubernetes cluster provisioned via [Sidero Omni](https://omni.janncot.com) (see **Omni Setup** below)
- `kubectl` works with the correct kubeconfig (placed at `kubeconfig` in repo root)
- Cloudflare account with domain and API token
- (Optional) NAS with NFS exports for `nfs-subdir` and `claude-code` extras

## Omni Cluster Setup

All clusters use **Cilium** as CNI (installed automatically by `task bootstrap:apps`). You must disable Omni's built-in flannel CNI before first boot.

### 1. Create Cluster in Omni UI

Omni UI → Clusters → Create Cluster

- **Cluster Name**: e.g. `jgu5`
- **Talos Version**: latest
- **Kubernetes Version**: matching version

### 2. Add MachineConfigPatch (required — before first boot)

In the cluster creation screen, add a Patch:

```yaml
cluster:
  network:
    cni:
      name: none
  coreDNS:
    disabled: true
```

This tells Talos to skip the built-in CNI **and** built-in coredns. Cilium + coredns will be installed from `jg-base` in step 5.

⚠️ This patch **must** be applied before the cluster first boots. If flannel or Omni's coredns is already installed, you must recreate the cluster.

### 3. Assign Nodes and Create

Add machines, assign control-plane / worker roles, then create. Nodes will be `NotReady` (no CNI yet) — this is expected.

### 4. Generate kubeconfig

```sh
# Install omnictl if not already installed
omnictl get clusters   # verify Omni access

# Download SA-based kubeconfig (TTL 1 year)
omnictl kubeconfig --service-account --user ferry133 --ttl 8760h \
  --cluster <cluster-name> kubeconfig-sa

# Copy to kubeconfig (mise.toml reads KUBECONFIG=kubeconfig)
cp kubeconfig-sa kubeconfig
```

See `CLAUDE.md` for how to create an Omni Service Account if you don't have one.

## Local Workstation Setup

### 1. Install Mise

Install the [Mise CLI](https://mise.jdx.dev/getting-started.html), then activate in your shell.

### 2. Install CLI tools

```sh
mise trust
mise install
```

### 3. Logout of registries (prevents auth issues)

```sh
docker logout ghcr.io
helm registry logout ghcr.io
```

## Cloudflare Configuration

### 1. Create API Token

Go to Cloudflare → My Profile → API Tokens → Create Token.

- Template: **Edit zone DNS**
- Permissions: `Zone - DNS - Edit` + `Account - Cloudflare Tunnel - Read`
- Scope: your account and zone

Save the token as `cloudflare_token` in `cluster.yaml`.

### 2. Create Cloudflare Tunnel

```sh
cloudflared tunnel login
cloudflared tunnel create --credentials-file cloudflare-tunnel.json kubernetes
```

The tunnel token is embedded into cluster secrets by `task configure`.

## Setup Steps

### 1. Initialize

```sh
task init
```

Generates: `cluster.yaml` (from sample), `age.key` (SOPS key), `github-deploy.key`, `github-push-token.txt`.

### 2. Fill in cluster.yaml

Edit `cluster.yaml` — all required fields are documented with comments. Reference `cluster.sample.yaml` for all available extras and optional fields.

### 3. Configure

```sh
task configure
```

Validates schema → renders Jinja2 templates → encrypts secrets → validates outputs.

Produces:
```
kubernetes/
  components/sops/cluster-secrets.sops.yaml   ← commit this
  flux/cluster/ks.yaml                        ← commit this
bootstrap/                                    ← gitignored; used by task bootstrap:apps
```

### 4. Commit and Push

```sh
git add kubernetes/components/sops/cluster-secrets.sops.yaml
git add kubernetes/flux/cluster/ks.yaml
git commit -m "chore: initial cluster configuration"
git push
```

### 5. Bootstrap

Installs Cilium → cert-manager → flux-operator → flux-instance in order:

```sh
task bootstrap:apps
```

After this, Flux takes over and syncs all base apps and selected extras from `jg-base`.
Nodes will become `Ready` once Cilium is deployed.

⚠️ Run this only once. After bootstrap, all changes go through Flux (see below).

## Post-Bootstrap Operations

### Force Flux Sync

```sh
task reconcile   # force Flux to re-sync from git
```

Or manually:

```sh
# Re-sync git source
flux reconcile source git flux-system -n flux-system

# Re-apply a specific Kustomization
flux reconcile ks <ks-name> -n flux-system
```

### After Changing cluster.yaml

```sh
task configure
# Re-apply the updated cluster-secrets:
sops -d kubernetes/components/sops/cluster-secrets.sops.yaml \
  | kubectl apply -n flux-system -f - --server-side
```

### Monitor Deployment

```sh
kubectl get pods --all-namespaces --watch
```

## GitHub Webhook (Optional)

For Flux to reconcile on `git push` instead of polling:

1. Get webhook path:
   ```sh
   kubectl -n flux-system get receiver github-webhook \
     --output=jsonpath='{.status.webhookPath}'
   ```

2. Full URL: `https://flux-webhook.${cloudflare_domain}/hook/<path>`

3. GitHub → Settings → Webhooks → Add webhook:
   - URL: above
   - Token: from `github-push-token.txt`
   - Content type: `application/json`
   - Events: push only

## Verification

```sh
flux check
flux get ks -A
flux get hr -A
```

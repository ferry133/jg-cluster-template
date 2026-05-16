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


## 🚀 Let's Go!

There are **6 stages** outlined below for completing this project, make sure you follow the stages in order.

### Stage 1: Hardware Configuration

For a **stable** and **high-availability** production Kubernetes cluster, hardware selection is critical. NVMe/SSDs are strongly preferred over HDDs, and **Bare Metal is strongly recommended** over virtualized platforms like Proxmox.

Using **enterprise NVMe or SATA SSDs on Bare Metal** (even used drives) provides the most reliable performance and rock-solid stability. Consumer **NVMe or SATA SSDs**, on the other hand, carry risks such as latency spikes, corruption, and fsync delays, particularly in multi-node setups.

**Proxmox with enterprise drives can work** for testing or carefully tuned production clusters, but it introduces additional layers of potential I/O contention — especially if consumer drives are used. Any **replicated storage** (e.g., Rook-Ceph, Longhorn) should always use **dedicated disks separate from control plane and etcd nodes** to ensure reliability. Worker nodes are more flexible, but risky configurations should still be avoided for stateful workloads to maintain cluster stability.

These guidelines provide a strong baseline, but there are always exceptions and nuances. The best way to ensure your hardware configuration works is to **test it thoroughly and benchmark performance** under realistic workloads.

### Stage 2: Machine Preparation

> [!IMPORTANT]
> If you have **3 or more nodes** it is recommended to make 3 of them controller nodes for a highly available control plane. This project configures **all nodes** to be able to run workloads. **Worker nodes** are therefore **optional**.
>
> **Minimum system requirements**
> | Role    | Cores    | Memory        | System Disk               |
> |---------|----------|---------------|---------------------------|
> | Control/Worker | 4 | 16GB | 256GB SSD/NVMe |

##
## 2 types of Baby k8s Clusters sources ---(A) Talos ---(B) Omni
##
## ---(A) Talos Baby Cluster Setup
1. Head over to the [Talos Linux Image Factory](https://factory.talos.dev) and follow the instructions. Be sure to only choose the **bare-minimum system extensions** as some might require additional configuration and prevent Talos from booting without it. Depending on your CPU start with the Intel/AMD system extensions (`i915`, `intel-ucode` & `mei` **or** `amdgpu` & `amd-ucode`), you can always add system extensions after Talos is installed and working.

2. This will eventually lead you to download a Talos Linux ISO (or for SBCs a RAW) image. Make sure to note the **schematic ID** you will need this later on.

3. Flash the Talos ISO or RAW image to a USB drive and boot from it on your nodes.

4. Verify with `nmap` that your nodes are available on the network. (Replace `192.168.1.0/24` with the network your nodes are on.)

    ```sh
    nmap -Pn -n -p 50000 192.168.1.0/24 -vv | grep 'Discovered'
    ```


## ---(B) Omni Baby Cluster Setup

All clusters use **Cilium** as CNI (installed automatically by `task bootstrap:apps`). You must disable Omni's built-in flannel CNI before first boot.

### 1. Create Installatoin ISO in Omni UI

Omni UI → Download Installation Media → Create New.    (If havn't create yet.)

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




### Stage 3: Local Workstation

> [!TIP]
> It is recommended to set the visibility of your repository to `Public` so you can easily request help if you get stuck.

1. Create a new repository by clicking the green `Use this template` button at the top of this page, then clone the new repo you just created and `cd` into it. Alternatively you can use the [GitHub CLI](https://cli.github.com/) ...

    ```sh
    export REPONAME="home-ops"
    gh repo create $REPONAME --template onedr0p/cluster-template --public --clone
    cd $REPONAME
    ```

2. **Install** the [Mise CLI](https://mise.jdx.dev/getting-started.html#installing-mise-cli) on your local workstation.

3. **Activate** Mise in your shell by following the [activation guide](https://mise.jdx.dev/getting-started.html#activate-mise).

4. Use `mise` to install the **required** CLI tools:

    ```sh
    mise trust
    pip install pipx
    mise install
    ```

   📍 _**Having trouble installing the tools?** Try unsetting the `GITHUB_TOKEN` env var and then run these commands again_

   📍 _**Having trouble compiling Python?** Try running `mise settings python.compile=0` and then run these commands again_

5. Logout of the GitHub Container Registry as this may cause authorization problems in future steps when using the public registry:

    ```sh
    docker logout ghcr.io
    helm registry logout ghcr.io
    ```

### Stage 4: Cloudflare configuration

> [!WARNING]
> If any of the commands fail with `command not found` or `unknown command` it means `mise` is either not installed, activated or it could be configured incorrectly.

1. Create a Cloudflare API token for use with cloudflared and external-dns by reviewing the official [documentation](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/) and following the instructions below.

   - Click the blue `Use template` button for the `Edit zone DNS` template.
   - Name your token `kubernetes`
   - Under `Permissions`, click `+ Add More` and add permissions `Zone - DNS - Edit` and `Account - Cloudflare Tunnel - Read`
   - Limit the permissions to a specific account and/or zone resources and then click `Continue to Summary` and then `Create Token`.
   - **Save this token somewhere safe**, you will need it later on.

2. Create the Cloudflare Tunnel:

    ```sh
    cloudflared tunnel login
    cloudflared tunnel create --credentials-file cloudflare-tunnel.json kubernetes
    ```


The tunnel token is embedded into cluster secrets by `task configure`.


### Stage 5: Cluster configuration

1. Generate the config files from the sample files:

```sh
task init
```

Generates: `cluster.yaml` (from sample), `age.key` (SOPS key), `github-deploy.key`, `github-push-token.txt`.

2. Fill out the `cluster.yaml` configuration file using the comments in it as a guide. Select & un-comment for all available extras and optional fields.
    ---(A) Talos baby cluster need to fill out the `nodes.yaml` as well


3. Template out the kubernetes and talos configuration files, if any issues come up be sure to read the error and adjust your config files accordingly.

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

4. Push your changes to git:
### 4. Commit and Push

   📍 _**Verify** all the `./kubernetes/**/*.sops.*` files are **encrypted** with SOPS_

    ```sh
    git add -A
    git commit -m "chore: initial commit :rocket:"
    git push
    ```

> [!TIP]
> Using a **private repository**? Make sure to paste the public key from `github-deploy.key.pub` into the deploy keys section of your GitHub repository settings. This will make sure Flux has read/write access to your repository.



### Stage 6: Bootstrap Talos, Kubernetes, and Flux

## ---(A) Talos baby cluster
> [!WARNING]
> It might take a while for the cluster to be setup (10+ minutes is normal). During which time you will see a variety of error messages like: "couldn't get current server API group list," "error: no matching resources found", etc. 'Ready' will remain "False" as no CNI is deployed yet. **This is normal.** If this step gets interrupted, e.g. by pressing <kbd>Ctrl</kbd> + <kbd>C</kbd>, you likely will need to [reset the cluster](#-reset) before trying again

1. Install Talos:

    ```sh
    just bootstrap talos
    ```

2. Push your changes to git:

    ```sh
    git add -A
    git commit -m "chore: add talhelper encrypted secret :lock:"
    git push
    ```

## ---(B) Omni baby cluster

### 1. Assign Nodes and Create cluster

In Omni UI, Cluster --> Create cluster
    Add machines, assign control-plane / worker roles, then create. Nodes will be `NotReady` (no CNI yet) — this is expected.

### 2. (Option) Generate kubeconfig with ServiceAccount

ferry133's Omni instance is self-hosted inside the `jcom` cluster (not exposed publicly). To use `omnictl` you must port-forward to it first and have a valid Service Account token in `~/.config/omni/env`.

```sh
# 1. Port-forward to the Omni service (requires jcom kubeconfig)
KUBECONFIG=~/coding/jcom/kubeconfig kubectl port-forward -n omni svc/omni 18080:8080 &

# 2. Load OMNI_ENDPOINT + OMNI_SERVICE_ACCOUNT_KEY
source ~/.config/omni/env
omnictl get clusters   # verify access

# 3. Generate a SA-based kubeconfig for the new cluster (positional output path)
omnictl kubeconfig ~/coding/<repo>/kubeconfig-sa \
  --cluster <cluster-name> \
  --service-account \
  --user ferry133 \
  --ttl 8760h

# 4. Place it where mise expects it (KUBECONFIG=./kubeconfig)
cp ~/coding/<repo>/kubeconfig-sa ~/coding/<repo>/kubeconfig
```

If you don't yet have an Omni Service Account or its token has expired, see `CLAUDE.md` ("Omni Service Account 設定") for the full SA-rotation procedure.

> jcom is Talos-from-scratch (not Omni-provisioned) and uses a Talos client-cert kubeconfig — it does **not** need this step.


## Check: Baby k8s cluster is ready for base/extras applicatoin instatllation

- Kubernetes cluster provisioned via [Sidero Omni](https://omni.janncot.com) (see **Omni Setup** below)
- `kubectl` works with the correct kubeconfig (placed at `kubeconfig` in repo root)
- Cloudflare account with domain and API token
- (Optional) NAS with NFS exports for `nfs-subdir` and `claude-code` extras


###
### Below now, both (A) Talos & (B) operation are the same.
###

### 3 Install cilium, coredns, spegel, flux and sync the cluster to the repository state:

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

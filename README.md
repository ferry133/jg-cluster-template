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

### Local Workstation

> [!TIP]
> It is recommended to set the visibility of your repository to `Public` so you can easily request help if you get stuck.

1. Create a new repository by clicking the green `Use this template` button at the top of this page, then clone the new repo you just created and `cd` into it. Alternatively you can use the [GitHub CLI](https://cli.github.com/) ...

    ```sh
    export REPONAME="home-ops"
    gh repo create $REPONAME --template ferry133/jg-cluster-template --public --clone
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

## Flux reconcile

### 1. GitHub Webhook

By default Flux will periodically check your git repository for changes. In-order to have Flux reconcile on `git push` you must configure GitHub to send `push` events to Flux.

1. Obtain the webhook path:

   📍 _Hook id and path should look like `/hook/12ebd1e363c641dc3c2e430ecf3cee2b3c7a5ac9e1234506f6f5f3ce1230e123`_

    ```sh
    kubectl -n flux-system get receiver github-webhook --output=jsonpath='{.status.webhookPath}'
    ```

2. Piece together the full URL with the webhook path appended:

    ```text
    https://flux-webhook.${cloudflare_domain}/hook/12ebd1e363c641dc3c2e430ecf3cee2b3c7a5ac9e1234506f6f5f3ce1230e123
    ```

3. Navigate to the settings of your repository on GitHub, under "Settings/Webhooks" press the "Add webhook" button. Fill in the webhook URL and your token from `github-push-token.txt`, Content type: `application/json`, Events: Choose Just the push event, and save.


## OMNI Cluster create
** How to create omni cluster without CNI (flanel) **
在 omni.janncot.com 建立叢集時，步驟如下：

### 1. 建立 Cluster
Omni UI → Clusters → Create Cluster

填入：

Cluster Name: jgu5
Talos Version: 選最新
Kubernetes Version: 選對應版本
### 2. 加入 MachineConfigPatch（關鍵）
在建立畫面找 Patches 或 Machine Config 區塊，加入一個新 patch：

```sh
cluster:
  network:
    cni:
      name: none
```
這告訴 Talos 不要裝任何內建 CNI，讓 Cilium 接管。

### 3. 加入節點
選擇你的 machines 並指定 control plane / worker 角色。

### 4. 確認並建立
建立後，節點會是 NotReady 狀態（正常，因為沒有 CNI），等 Flux 部署 Cilium 後才會變 Ready。

⚠️ Patch 必須在叢集第一次 boot 前設好。 如果先建立叢集再加 patch，flannel 已經裝上去了，需要重建才能換掉。

建好後回來接著跑 task bootstrap:apps，它會裝 Cilium → nodes 變 Ready → Flux 接手同步其餘 apps。


## Setup Steps

### 1. Initialize

```sh
task init
```

This generates: `cluster.yaml` (from sample), `age.key` (SOPS encryption key), `github-deploy.key`, `github-push-token.txt`.

### 2. Fill in cluster.yaml

Edit cluster.yaml — fill in all required values
Reference kubernetes/components/sops/cluster-secrets.sample.yaml in jg-base for variable keys


### 3. Task Configure

```sh
task configure
```

### 4. Commit and push

```sh
git add kubernetes/components/sops/cluster-secrets.sops.yaml
git add flux/cluster/ks.yaml
git commit -m "chore: initial cluster configuration"
git push
```


### 5. Bootstrap Flux

```sh
task bootstrap:apps   # install Flux and sync to git state
```
** Above command might not able to be executed repeatly. **

The alternative:  Once bootstrapped, everything goes through Flux reconcile:

```sh
  # Force re-sync git source
  flux reconcile source git flux-system -n flux-system
```

```sh
  # Force re-apply a specific KS
  flux reconcile ks <ks-name> -n flux-system
```

  # After changing cluster.yaml — re-apply cluster-secrets
```sh
  sops -d kubernetes/components/sops/cluster-secrets.sops.yaml \
    | kubectl apply -n flux-system -f - --server-side
```sh

  One-liner rule: bootstrap once, then all changes go through git → Flux → cluster.




May keep watching the deployment progress:
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

# CLAUDE.md — jg-cluster-template / per-user cluster repo

## 三 Repo 架構

每個 extra app 橫跨三個 repo，**缺一不可**：

| Repo | 職責 |
|------|------|
| `ferry133/jg-base` | App 的 K8s manifests（ks.yaml + app/ 資料夾） |
| `ferry133/jg-cluster-template`（此 repo） | CUE schema、cluster-secrets 模板、cluster.sample.yaml 文件 |
| 各 user repo（此 repo / jgu4 等） | cluster.yaml 填值 → task configure → push |

## ⚠️ 新增或修改 Extra App 的完整 Checklist

不論從哪個 repo 起頭，都必須同步完成以下所有步驟：

### Step 1 — `jg-base`：新增 App manifests
- [ ] `kubernetes/apps/extras/<ns>/<app>/kustomization.yaml`（resources: [./ks.yaml]）
- [ ] `kubernetes/apps/extras/<ns>/<app>/ks.yaml`（Flux Kustomization，sourceRef: jg-base）
- [ ] `kubernetes/apps/extras/<ns>/<app>/app/`：Deployment、Service、HTTPRoute、PVC、Secret 等
- [ ] Secret 值用 `${VAR_NAME}` 佔位符（由 cluster-secrets postBuild substituteFrom 注入）

### Step 2 — `jg-cluster-template`：同步更新 Schema 與模板
- [ ] `.taskfiles/template/resources/cluster.schema.cue`：加入新 optional 欄位（`field?: string`）
- [ ] `templates/config/kubernetes/components/sops/cluster-secrets.sops.yaml.j2`：加入 `VAR_NAME: "#{ var_name | default('') }#"` 行
- [ ] `cluster.sample.yaml`：在 extras 清單加入說明，並加入 config 欄位範例（加 `#` 注解）

### Step 3 — User Repo（此 repo）：啟用 App
- [ ] `cluster.yaml`：在 `extras` 加入 `<ns>/<app>`，填入對應 config 欄位的實際值
- [ ] `task configure --yes`：重新生成 `kubernetes/flux/cluster/ks.yaml` 和 `cluster-secrets.sops.yaml`
- [ ] commit & push（三個 repo 依序：jg-base → jg-cluster-template → user repo）

## 命名慣例

- Secret 環境變數：以 app 名稱為 prefix，全大寫，e.g. `SYNOPHOTO_AUTH0_DOMAIN`
- CUE schema 欄位：小寫 snake_case，e.g. `synophoto_auth0_domain?: string`
- `cluster.yaml` 欄位：同 CUE schema 欄位名稱

## kubectl Access（產生此 repo 後需填入）

```sh
kubectl --kubeconfig ~/coding/<repo>/kubeconfig-sa <command>
```

詳細設定方式見下方 Omni SA 建立流程。

---

## Omni Service Account 建立 / 更新流程

適用情境：Omni 升級後 SA key 失效、第一次建立新 user repo。

### Step 1 — 建立或更新 SA（Omni UI）

1. 開啟 `https://omni.janncot.com` → **Settings → Service Accounts**
2. 若舊 SA `claude-code` 存在且失效 → 點 **…** → **Destroy**
3. **Create Service Account**：Name `claude-code`、Role `Admin`、TTL `1 year`
4. 建立後複製完整 SA token（`eyJ...` 格式）

### Step 2 — 更新 ~/.config/omni/env

```sh
cat > ~/.config/omni/env << 'ENVEOF'
# SA: claude-code@serviceaccount.omni.sidero.dev, Admin, renewed <date>
# NOTE: OMNI_ENDPOINT 指向 localhost，需先開 port-forward：
#   KUBECONFIG=~/coding/jcom/kubeconfig kubectl port-forward -n omni svc/omni 18080:8080 &
export OMNI_ENDPOINT=grpc://localhost:18080
export OMNI_SERVICE_ACCOUNT_KEY=<貼上 SA token>
ENVEOF
```

### Step 3 — 開 port-forward 並測試

```sh
KUBECONFIG=~/coding/jcom/kubeconfig kubectl port-forward -n omni svc/omni 18080:8080 &
source ~/.config/omni/env
omnictl get clusters   # 應列出所有 cluster
```

### Step 4 — 為每個 cluster 產生 kubeconfig-sa

```sh
source ~/.config/omni/env
omnictl kubeconfig ~/coding/<repo>/kubeconfig-sa \
  --cluster <cluster-name> \
  --service-account \
  --user ferry133 \
  --ttl 8760h

# Omni-managed cluster（如 jgu5）：用 kubeconfig-sa 覆蓋 kubeconfig
# （.mise.toml 的 KUBECONFIG 指向 kubeconfig）
cp ~/coding/<repo>/kubeconfig-sa ~/coding/<repo>/kubeconfig
```

### Step 5 — 驗證

```sh
cd ~/coding/<repo>
mise x -- kubectl get nodes
```

### 注意事項

- `jcom` 使用 Talos client cert kubeconfig，**不需要** kubeconfig-sa
- Omni UI 的 Edit User 對話框只有 Role，沒有 Public Keys 管理（v1.7.x 已移除）
- PGP user key 有 lifetime 限制（Omni 限制從現在起約數小時），不適合長期使用，改用 SA

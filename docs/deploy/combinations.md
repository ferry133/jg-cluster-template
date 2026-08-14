# 叢集組合與各階段 SOP

**讀者**：交付與維運這項產品的人——員工、或代為執行的 AI agent。假設你不認識這套系統，
也沒有任何人可以問。

**這份文件做什麼**：告訴你手上這座叢集是哪一種組合，每個階段各要做什麼、誰做、**怎麼確認
真的做到了**。

**這份文件不做什麼**：不複述任何程序。每一個「怎麼做」都指向唯一寫下它的地方——分岔的
文件必然有一份是錯的，而錯的那份會被照著執行。

---

## 0. 三個角色

| 角色 | 是誰 | 邊界 |
|------|------|------|
| **客戶** | 收到硬體的人 | 只做物理動作。不輸入任何值、不看任何指令 |
| **Operator** | 員工 | 執行本文件所有步驟，持有跨系統憑證 |
| **Agent** | AI（如 Claude Code） | 可執行絕大多數步驟，但有五件事**必須先問人**，見 §2 |

---

## 1. 核心原則：每一步都要有驗證指令

這是本文件與一般安裝說明最大的差別，也是它能被 agent 執行的前提。

**在這套系統裡，「看起來好了」和「好了」經常不是同一件事。** 以下每一項都是實際發生過、
且當下沒有任何跡象的：

| 看起來 | 實際上 |
|--------|--------|
| `git push` 成功 | 叢集還不知道。cluster-secrets 是獨立的 Kustomization，有自己的節奏 |
| Kustomization `suspend: true` | 它已經套用出去的東西**全部還在跑**。suspend 不會 prune |
| Deployment `READY 2/2` | 第二個 replica 已經 `Pending` 26 分鐘（新 RS 滿足了，卡住的是 surge 出來的那個）|
| 18 個 pod 全部 `Running` | HelmRelease 已 `Stalled` 40 小時，且不會自己重試 |
| 健檢回報 `✅ Off-site backup not configured` | 這座叢集**沒有異地備份** |
| 從筆電 `dig` 到路由器有回應 | 查詢在半路被攔截，你量到的是自己網段的 DNS |
| Longhorn pod 全部就緒 | 缺 Talos extension 時它掛載不了任何 volume |

**所以：本文件每一個步驟都附驗證指令與預期輸出。沒有通過驗證的步驟等於沒做。**
不要用「應該可以了」結束一個步驟。

---

## 2. Agent 必須先問人的五件事

其餘步驟 agent 可自行執行。這五件不行：

1. **刪除任何 PVC 或 PV** — 即使更大的任務已被核准
2. **刪除 namespace 或 Kustomization** — 先確認它已套用出去的東西
3. **輸入任何憑證** — 密碼、API token、金鑰一律由人操作
4. **push 到會觸發 Flux 的分支** — 先讓人看過渲染出的 diff
5. **對既有叢集執行破壞性 `kubectl` / `talosctl`** — reset、drain、force delete

判準：**這個動作出錯時，能不能靠重跑救回來？** 不能就先問。

---

## 3. 維度有幾個

常被說成三個（單/多節點、有/無 NAS、Omni/Talos），但那三個大半是**同一個主軸的後果**。
權威來源是 `.taskfiles/template/resources/cluster.schema.cue`——**以它為準，不是本表**。

| # | 維度 | 值 | 誰決定 | 代價付在哪個階段 |
|---|------|----|--------|------------------|
| 1 | `deployment_profile` | `appliance` / `prosumer` / `full` | 賣的是什麼 | **全部**——它推導出下面好幾項 |
| 2 | `single_node` | true / false | 硬體採購 | 前期準備 |
| 3 | `storage_backend` | `local-path` / `nfs` / `replicated` | 客戶有沒有 NAS | 前期準備 |
| 4 | `provisioning_path` | `omni` / `talos` | 有沒有 Omni 可用 | 安裝過程 |
| 5 | `replicated_storage` | true / false | 資料庫要不要能跨節點漂移 | **前期準備**（見下） |
| 6 | `db_storage_class` | class 名稱 | 資料庫落在哪一層 | 前期準備 + 遷移 |
| 7 | **路由器能力** | 條件式轉發 / DHCP / 逐筆 A record | 客戶現有設備 | 安裝過程 |
| 8 | 異地備份 + `age_key_escrowed` | 有 / 無 | profile 強制或自選 | 前期準備 + 維運 |
| 9 | `cilium_native_routing` | true / false | 這座叢集是否託管 Omni | 前期準備 |
| 10 | `extras` | 清單 | 客戶要跑什麼 | 前期準備 |

### 兩個最常被放錯階段的判斷

**#5 `replicated_storage` 是前期準備，不是維運。** Longhorn 需要每個節點帶
`iscsi-tools` 與 `util-linux-tools` 兩個 Talos system extension，加上 `/var/lib/longhorn`
的 rshared 掛載——**沒有任何 Kubernetes manifest 裝得起來**。事後才要就得換 schematic
並逐台重開機。

> **不要把既有叢集的成功當成通則。** 曾有一座叢集事後啟用而沒付代價，只因為它的 schematic
> 本來就帶著那兩個 extension。那是運氣。出貨前**一律**用 §5 的驗證指令確認。

**#8 `age.key` escrow 是前期準備，不是交接時才做。** 備份加密到叢集自己的公鑰，
`age.key` 是唯一能讀它的東西。金鑰若只存在於備份要對抗的那顆碟上，備份就是沒人打得開的
密文——**比沒有備份更糟，因為它看起來像保護**。

---

## 4. CUE 已經替你排除的組合

這些在 `task configure` 的 `cue vet` 就會失敗，**在渲染之前**，所以不會產出半套設定。
不需要背，但知道它們存在可以省下爭論：

| 組合 | 為什麼被拒 |
|------|-----------|
| `appliance` + 多節點 | appliance 定義上是單節點 |
| `appliance` + NAS | 客戶端零欄位，沒有人可以填 NAS 位址 |
| `appliance` + 手動 Talos | 手動路徑要求逐節點 IP / NIC / 磁碟選擇器，零 IT 客戶供不出來 |
| `appliance` + 宣告 LB 位址 | 位址是執行期探測出來的，填了也沒人讀 |
| `appliance` 缺異地備份或 escrow | 單碟無冗餘，資料無保護的叢集不該渲染得出來 |
| 單節點 + `replicated` | 同一顆碟上的兩份副本：付了 Longhorn 的代價，沒有任何保護 |
| 多節點 + node-local 且未承認 | 必須明寫 `accept_node_pinning`，且不能寫 `false` |
| `nfs` 但沒填 `nas_server` / `nas_path` | 沒有 NAS 可供裝 |
| `omni` + 非空 `nodes` ／ `talos` + 空 `nodes` | 節點清單只在手動路徑有意義 |

---

## 5. 前期準備

### 5.1 客戶訪談 → 推導組合

Operator 問這六題，其餘欄位由答案推導。**六題都要有答案才能進入下一步**——
猜一個然後之後修，代價通常是重灌。

| # | 問客戶 | 決定 |
|---|--------|------|
| 1 | 你們有沒有人會操作系統？出問題誰處理？ | `deployment_profile` |
| 2 | 幾台機器？可以停機多久？ | `single_node` |
| 3 | 有沒有 NAS／檔案伺服器？型號與位址？ | `storage_backend`、`nas_*` |
| 4 | 要跑資料庫嗎？（含 FreePBX、Home Assistant 等內建資料庫的服務） | `db_storage_class`、`accept_node_pinning`、`replicated_storage` |
| 5 | **路由器是什麼廠牌型號？** | 安裝當天用哪一種 DNS 做法（§6.4）|
| 6 | 網域在哪裡管理？ | `cloudflare_domain`、token |

> 第 5 題最常被跳過，而它決定安裝當天一個必做步驟能不能完成。**到場前就要問到**——
> 到現場才發現路由器不支援，是一趟白跑。

### 5.2 恆定步驟（所有組合）

| 步驟 | 誰 | 驗證 |
|------|----|------|
| 決定 `cluster_name` 與 `cloudflare_domain` | Operator | — |
| Cloudflare：建 tunnel + API token | Operator | `cloudflare-tunnel.json` 存在且含 `TunnelID` |
| 從 `jg-cluster-template` 產生 per-user repo | Operator / Agent | repo 可 clone |
| `task init` | Operator / Agent | `age.key`、`github-deploy.key`、`github-push-token.txt` 皆存在 |
| 填 `cluster.yaml` | Operator | — |
| `task configure` | Operator / Agent | **exit 0**。它會跑 `cue vet` + `kubeconform`，兩者任一失敗即中止 |

步驟細節見 [`docs/deploy/manual.md`](manual.md) Stage 3–5。

### 5.3 依維度分歧

| 條件 | 額外要做 | 驗證 |
|------|---------|------|
| `profile: appliance` | `backup_r2_*` 四欄與 `age_key_escrowed` 為必填；不可填 LB 位址 | `cue vet` 會擋。escrow 另需 §5.4 |
| `prosumer` / `full` | 在 LAN 挑 4 個未使用位址 | `nmap -sn <cidr>` 確認無回應；既有叢集另跑 `./scripts/check-lb-pool-covers-live.py` |
| `storage_backend: nfs` | NAS 上開好 export 與權限 | 從節點 `showmount -e <nas>` 看得到該 export |
| `provisioning_path: talos` | 填 `nodes.yaml`（每節點 name / address / controller / disk / mac_addr / schematic_id）| 實際掃描硬體取得，不可推測 |
| `provisioning_path: omni` | 在 Omni 建 schematic 與 ISO（內嵌 SideroLink token）| ISO 可開機且機器出現在 Omni |
| `replicated_storage: true` | **schematic 必須含 `iscsi-tools` + `util-linux-tools`** | 見 §5.4 |
| 多節點 + node-local | 明寫 `accept_node_pinning: true` | `cue vet` 會擋。但它問的是「你知道 pod 會被釘死在單一節點嗎」——**要真的讀懂再填** |
| 託管 Omni | `cilium_native_routing: true`，所有節點須在同一 L2 網段 | — |
| 有 block-tier extra | `claudecode/postgres`、`default/mariadb`、`default/postgres`、`freepbx/freepbx` 會落在 block tier，即使有 NAS | — |

### 5.4 兩個必須實測的前置條件

**Longhorn 前置條件**（只在 `replicated_storage: true` 時）——叢集起來後立刻驗：

```sh
kubectl get nodes.longhorn.io -n longhorn-system -o json | jq -r \
  '.items[] | .metadata.name as $n | .status.conditions[] | [$n,.type,.status] | @tsv'
```

每個節點的 `RequiredPackages`、`MountPropagation`、`KernelModulesLoaded`、`Multipathd`
**都必須是 `True`**。任何一個 `False` 就停下來換 schematic——繼續下去 pod 會起來、回報
健康、然後掛載不了任何 volume。

**age.key escrow**——依 [`docs/operations/age-key-escrow.md`](../operations/age-key-escrow.md)
存出副本後，用副本驗證公鑰：

```sh
age-keygen -y <escrow 副本路徑>   # 輸出須與 .sops.yaml 裡的 age 公鑰逐字相同
```

被截斷的金鑰副本看起來和好的一模一樣。**不比對就等於沒有 escrow。**

---

## 6. 安裝過程

### 6.1 恆定步驟

| 步驟 | 誰 | 驗證 |
|------|----|------|
| 機器上架、接網路與電源 | 客戶或 Operator | — |
| Talos 上機 | 依路徑，見 §6.2 | 節點 `Ready` |
| `task bootstrap:apps` | Operator / Agent | exit 0 |
| 等 Flux 收斂 | — | 見 §6.3 |
| 設定路由器 DNS | Operator | 見 §6.4 |
| 全叢集健檢 | Operator / Agent | 見 §6.5 |

### 6.2 依維度分歧

| 條件 | 做法 |
|------|------|
| `profile: appliance` | **客戶只做三個物理動作**：[`README-zero-IT.md`](../../README-zero-IT.md)。其餘全部遠端，客戶不輸入任何值 |
| `provisioning_path: omni` | 機器插電後自行回連；Operator 在 Omni UI assign nodes → create cluster。見 [`manual.md`](manual.md) Stage 6 (B) |
| `provisioning_path: talos` | `task bootstrap:talos` 一次完成 secret → genconfig → apply → bootstrap → kubeconfig。見 [`manual.md`](manual.md) Stage 6 (A) |
| `profile: appliance` | 設定路由器**之前**先釘住 `lan_shared_addr`——位址一旦寫進路由器就是外部契約，探測重選會讓它指向空氣 |
| `storage_backend: nfs` | 驗證節點到 NAS 可達且權限正確 |

### 6.3 驗證 Flux 真的收斂

```sh
# 兩者都必須「沒有輸出」——有輸出就是有東西沒 Ready
kubectl get kustomization -A --no-headers | awk '$4!="True"'
kubectl get helmrelease   -A --no-headers | awk '$4!="True"'
```

⚠️ **`Ready=False` 的 HelmRelease 不一定會自己好。** 若 `status.conditions` 出現
`Stalled` / `MissingRollbackTarget`，表示它兩次都失敗、沒有可回滾的目標，helm-controller
**不會再重試**——必須 `flux reconcile helmrelease <name> -n <ns> --force`。

### 6.4 路由器 DNS——所有組合都要做

內網名稱只有 k8s-gateway 答得出來（Cloudflare 拒絕為它託管的 zone 提供 RFC1918 答案），
而 resolver 只有被指向才會被問到。三種做法與取捨見
[`docs/operations/router-dns.md`](../operations/router-dns.md)。

| 客戶路由器 | 用哪一種 | 失效時的影響範圍 |
|-----------|---------|-----------------|
| dnsmasq 系（UniFi、OpenWrt、pfSense） | **條件式轉發**——只送 `<domain>` 給叢集 | 只有內網名稱 |
| 支援自訂 DNS record | 逐筆 A record | 只有沒建到的名稱 |
| 只有 DHCP（多數消費級） | DHCP 發 k8s-gateway 位址，**務必同時設 secondary** | **全屋 DNS** |

**驗證必須從叢集內部做**，不能從自己的筆電——跨網段的 53 埠常被中途攔截，你會量到自己
網段的 DNS 而不是客戶的路由器：

```sh
kubectl run dns-check --rm -it --image=alpine:3.20 --restart=Never -- sh -c \
  'apk add --no-cache bind-tools >/dev/null 2>&1;
   dig +short @<router-ip> internal.<domain> A;
   dig +short @<router-ip> github.com A'
```

第一行要回叢集的內網位址；第二行要正常回外部位址（證明你沒有把整個 DNS 導進叢集）。

> ⚠️ **已知缺口**：健檢問的是路由器自己解不解得出內網名稱，所以第三種做法下它**永遠 FAIL**。
> 而第三種正是多數消費級路由器唯一能做的。詳見 `deployment-profiles` D45 / task 5.7
> ——**修法尚未決定，不要順手改掉那個檢查**。

### 6.5 交付前的最後一關

手動跑一次每日健檢，**不要等隔天**：

```sh
kubectl create job -n monitoring daily-check-preflight --from=cronjob/daily-check
kubectl logs -n monitoring job/daily-check-preflight | tail -30
```

要看到 `Exit FAIL_COUNT=0`。逐行讀輸出——**綠勾不代表沒問題**，例如
`✅ Off-site backup not configured` 的意思是這座叢集沒有異地備份。

---

## 7. 上線維運

### 7.1 恆定

| 項目 | 機制 | 驗證 / 節奏 |
|------|------|------------|
| 每日健檢 | `monitoring/daily-check`，08:00 Asia/Taipei，Gmail SMTP + healthchecks.io dead-man switch | 每天有信；**沒收到信也是異常** |
| 設定變更 | 改 `cluster.yaml` → `task configure` → commit → push | push 後**必須確認叢集已套用**，見 §7.3 |
| 模板漂移 | `./scripts/check-template-drift.py <cluster-repo>` | 建議每月。漂移是靜默的 |
| 強制同步 | `task reconcile` | — |

### 7.2 依維度分歧

| 條件 | 維運差異 |
|------|---------|
| `profile: appliance` | 異地備份與 escrow 是強制的 |
| `full` / `prosumer` | 備份是**選配**——而選配的東西沒有人會主動去選。交付時就該當成必做 |
| `replicated_storage: true` | 移除遠比安裝麻煩，動它之前讀 [`replicated-storage.md`](../operations/replicated-storage.md) |
| 資料庫仍在 NFS | 失效模式是**靜默損毀**，唯一救援是備份 |
| `provisioning_path: talos` | `task talos:apply-node IP=<ip>` / `upgrade-node` / `upgrade-k8s` |
| `provisioning_path: omni` | 升級在 Omni UI |
| 多節點 + node-local | 失去任一節點就同時失去資料與重啟的能力 |

### 7.3 push 之後怎麼確認叢集知道了

**push 不等於 reconcile。** 要改的值若會被下一步用到（例如換 storage class），
必須先把值從叢集上讀出來確認：

```sh
flux reconcile kustomization cluster-secrets --with-source
kubectl get secret cluster-secrets -n flux-system \
  -o jsonpath='{.data.<KEY>}' | base64 -d; echo
```

曾有一次刪 PVC 後 Flux 立刻用**尚未更新的** cluster-secrets 重建它，而
`storageClassName` immutable，改不回來。見 `deployment-profiles` D38。

### 7.4 換 storage class（dump / restore）

`storageClassName` 是 immutable，所以搬遷不是重新渲染，是 dump / restore。順序：

1. 改 `cluster.yaml` → `task configure` → push
2. **確認叢集上的值已更新**（§7.3）
3. `pg_dump`
4. 刪 PVC（**agent 到這裡必須先問人**）
5. 等 Flux 用新值重建
6. restore，逐表比對列數

跳過第 2 步的後果見 D38。

---

## 8. 產品化前還缺的東西

誠實列出，因為**「以為有」比「知道沒有」更危險**：

| 缺口 | 歸屬 | 影響 |
|------|------|------|
| appliance 交付的 operator runbook | `factory-agent`（0/61） | 目前交付靠人記憶跨四個外部系統 |
| 客戶 onboarding 溝通管道 | `zero-it-onboarding`（16/50） | 客戶出問題時沒有標準管道 |
| 消費級路由器下的健檢做法 | `deployment-profiles` 5.7 / D45 | **每一台這樣出貨的機器都會帶著一個永遠紅的健檢** |
| 還原演練與還原程序文件 | `deployment-profiles` 8.3 / 8.4 | 備份的 restore 半邊**從未被執行過** |
| 交接演練 | `factory-agent` §6 | 「客戶隨時能拿回鑰匙」目前只是口頭承諾 |

---

## 附錄：參考部署

以下是既有叢集，可作為各組合的實例參考。**它們是例子，不是定義**——定義在 CUE schema。

| | profile | 節點 | bulk | 供裝 | Longhorn | DB 落在 | 異地備份 |
|---|---|---|---|---|---|---|---|
| `jgt-appliance` | `appliance` | 1 | `local-path` | Omni | — | `local-path` | ✅ |
| `jcom` | `full` | 1 | `nfs` | 手動 Talos | — | `local-path` | ❌ |
| `jg-jiahd` | `full` | 3 | `nfs` | Omni | ✅ | `sc-nas`（未搬） | ❌ |

**只有 appliance 有異地備份，因為只有它被 CUE 強制。** 這就是「選配」在實務上的意思，
也是 §7.2 說交付時要把它當必做的理由。

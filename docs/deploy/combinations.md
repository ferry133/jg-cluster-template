# 叢集組合與各階段 SOP

這份文件回答一個問題：**手上這座叢集是哪一種組合，每個階段各要做什麼。**

它**只做路由，不複述程序**。每一個「怎麼做」都指向唯一寫下它的地方——分岔的文件
必然有一份是錯的，而錯的那份會被照著執行。

---

## 1. 維度有幾個

常被說成三個（單/多節點、有/無 NAS、Omni/Talos），但那三個大半是**同一個主軸的後果**。
權威來源是 `.taskfiles/template/resources/cluster.schema.cue`。

| # | 維度 | 值 | 誰決定 | 代價付在哪個階段 |
|---|------|----|--------|------------------|
| 1 | `deployment_profile` | `appliance` / `prosumer` / `full` | 業務決定賣什麼 | **全部**——它推導出下面好幾項 |
| 2 | `single_node` | true / false | 硬體採購 | 前期準備 |
| 3 | `storage_backend` | `local-path` / `nfs` / `replicated` | 客戶有沒有 NAS | 前期準備 |
| 4 | `provisioning_path` | `omni` / `talos` | 有沒有 Omni 可用 | 安裝過程 |
| 5 | `replicated_storage` | true / false | 資料庫要不要能跨節點漂移 | **前期準備**（見下） |
| 6 | `db_storage_class` | class 名稱 | 資料庫落在哪一層 | 前期準備 + 遷移 |
| 7 | **路由器能力** | 條件式轉發 / DHCP / 逐筆 A record | 客戶現有設備 | 安裝過程 |
| 8 | 異地備份 + `age_key_escrowed` | 有 / 無 | profile 強制或自選 | 前期準備 + 維運 |
| 9 | `cilium_native_routing` | true / false | 這座叢集是否託管 Omni | 前期準備 |
| 10 | `extras` | 清單 | 客戶要跑什麼 | 前期準備 |

### 兩個容易被放錯階段的維度

**#5 `replicated_storage` 是前期準備，不是維運。** Longhorn 需要每個節點帶
`iscsi-tools` 與 `util-linux-tools` 兩個 Talos system extension 加上 `/var/lib/longhorn`
的 rshared 掛載，而**沒有任何 Kubernetes manifest 裝得起來**。事後才要就得換 schematic
並逐台重開機。少了它們的失敗形狀特別壞：pod 起得來、回報健康、然後掛載不了任何 volume。

> jg-jiahd 是意外的反例——它的 Omni schematic 一直帶著那兩個 extension，所以事後才啟用
> 也沒付代價。**不要把那個運氣當成通則。**

**#7 路由器能力不在 schema 裡，但它決定安裝當天的一個步驟。** 內網名稱要能解，只能靠
把某樣東西指向 k8s-gateway，而做法依路由器能力分三種——詳見
[`docs/operations/router-dns.md`](../operations/router-dns.md)。

---

## 2. CUE 已經替你排除的組合

這些在 `task configure` 的 `cue vet` 就會失敗，**在渲染之前**，所以不會產出半套設定。
不需要記，但知道它們存在可以省下爭論：

| 組合 | 為什麼被拒 |
|------|-----------|
| `appliance` + 多節點 | appliance 定義上是單節點 |
| `appliance` + NAS | 客戶端零欄位，沒有人可以填 NAS 位址 |
| `appliance` + 手動 Talos | 手動路徑要求逐節點的 IP / NIC / 磁碟選擇器，零 IT 客戶供不出來 |
| `appliance` + 宣告 LB 位址 | 位址是執行期探測出來的，填了也沒人讀 |
| `appliance` 缺異地備份或 escrow | 單碟無冗餘，資料無保護的叢集不該渲染得出來 |
| 單節點 + `replicated` | 同一顆碟上的兩份副本：付了 Longhorn 的代價，沒有任何保護 |
| 多節點 + node-local 且未承認 | 必須明寫 `accept_node_pinning`，且不能寫 false |
| `nfs` 但沒填 `nas_server` / `nas_path` | 沒有 NAS 可供裝 |
| `omni` + 非空 `nodes` ／ `talos` + 空 `nodes` | 節點清單只在手動路徑有意義 |

---

## 3. 實際存在的四種形狀

每一種都有一座活的叢集，可以直接去看：

| | `jgt-appliance` | `jcom` | `jg-jiahd` | `genie1` |
|---|---|---|---|---|
| profile | `appliance` | `full` | `full` | **未遷移** |
| 節點 | 1 | 1 | 3 | — |
| bulk 儲存 | `local-path` | `nfs` | `nfs` | — |
| 供裝 | Omni | **手動 Talos** | Omni | — |
| Longhorn | — | — | ✅ | — |
| 資料庫落在 | `local-path` | `local-path` | `sc-nas`（**尚未搬**） | — |
| 異地備份 | ✅ | ❌ | ❌ | ❌ |
| 託管 Omni | — | ✅ | — | — |

兩件從這張表直接讀得出來的事：

1. **只有 appliance 有異地備份**，因為只有它被 CUE 強制。三座 `full` 叢集全都沒有——
   選配的東西沒有人會主動去選。
2. **genie1 還沒遷移到 profile schema**，是第三支血脈（`reconcile-jcom-lineage` 2b.5）。

---

## 4. 前期準備

### 恆定（所有組合都要）

1. 決定 `cluster_name` 與 `cloudflare_domain`
2. Cloudflare：建 tunnel（產出 `cloudflare-tunnel.json`）與 API token
3. 從 `jg-cluster-template` 產生 per-user repo
4. `task init` → 產生 `cluster.yaml`、`age.key`、deploy key、push token
5. 填 `cluster.yaml` → `task configure`

步驟細節見 [`docs/deploy/manual.md`](manual.md) Stage 3–5。

### 依維度分歧

| 條件 | 額外要做的事 |
|------|-------------|
| `profile: appliance` | `backup_r2_*` 四欄與 `age_key_escrowed` 為**必填**；不可填任何 LB 位址 |
| `profile: prosumer` / `full` | 先在 LAN 上挑出 **4 個未使用位址**（API / envoy-internal / k8s-gateway / cloudflare） |
| `storage_backend: nfs` | 必填 `nas_server` + `nas_path`；NAS 上先開好 export 與權限 |
| `provisioning_path: talos` | 填 `nodes.yaml`：每節點 name / address / controller / disk / mac_addr / schematic_id。**要先實際掃描硬體** |
| `provisioning_path: omni` | 在 Omni 建 schematic 與 ISO（內嵌 SideroLink token），準備 MachineConfigPatch |
| `replicated_storage: true` | **schematic 必須含 `iscsi-tools` + `util-linux-tools`**。這一步做錯要重灌，見 [`replicated-storage.md`](../operations/replicated-storage.md) |
| 多節點 + node-local | 明寫 `accept_node_pinning: true`——它問的是「你知道 pod 會被釘死在單一節點嗎」 |
| 這座叢集要託管 Omni | `cilium_native_routing: true`，且所有節點須在同一 L2 網段 |
| 有 block-tier extra | `claudecode/postgres`、`default/mariadb`、`default/postgres`、`freepbx/freepbx` 會落在 block tier，即使叢集有 NAS |

---

## 5. 安裝過程

### 恆定

1. 機器上架、接網路與電源
2. Talos 上機（兩條路徑做法不同，見下）
3. `task bootstrap:apps` → Cilium、cert-manager、Flux
4. 等 Flux 全綠
5. **設定路由器 DNS**（見下）

### 依維度分歧

| 條件 | 做法 |
|------|------|
| `profile: appliance` | **客戶只做三個物理動作**：[`README-zero-IT.md`](../../README-zero-IT.md)。其餘全部遠端，客戶不輸入任何值 |
| `provisioning_path: omni` | 機器插電後自行回連；operator 在 Omni UI assign nodes → create cluster。見 [`manual.md`](manual.md) Stage 6 (B) |
| `provisioning_path: talos` | `task bootstrap:talos` 一次完成 secret → genconfig → apply → bootstrap → kubeconfig。見 [`manual.md`](manual.md) Stage 6 (A) |
| `profile: appliance` | 設定路由器**之前**先釘住 `lan_shared_addr`——位址一旦寫進路由器就是外部契約，探測重選會讓它指向空氣 |
| `storage_backend: nfs` | 驗證節點到 NAS 可達，且 export 權限正確 |

### 路由器 DNS——所有組合都要，做法依設備而定

內網名稱只有 k8s-gateway 答得出來（Cloudflare 拒絕為它託管的 zone 提供 RFC1918 答案），
而 resolver 只有被指向才會被問到。三種做法與取捨見
[`docs/operations/router-dns.md`](../operations/router-dns.md)。

| 路由器 | 用哪一種 |
|--------|---------|
| UniFi / OpenWrt / pfSense（dnsmasq 系） | **條件式轉發**——只送 `<domain>` 給叢集。失效範圍最窄 |
| 支援自訂 DNS record | 逐筆 A record。缺點：以後每加一個 HTTPRoute 都要有人記得回來補，漏補沒有提示 |
| 便宜路由器（只有 DHCP） | DHCP 發 k8s-gateway 位址，**務必同時設 secondary**。代價：全屋查詢都經過叢集 |

> ⚠️ **已知缺口**：daily-check 問的是路由器自己解不解得出內網名稱，所以第三種做法下它
> **永遠 FAIL**。而第三種正是 appliance 的出貨形狀。詳見 `deployment-profiles` D45 / task 5.7
> ——**修法尚未決定，不要順手改掉那個檢查**。

---

## 6. 上線維運

### 恆定

| 項目 | 機制 |
|------|------|
| 每日健檢 | `monitoring/daily-check` CronJob，08:00 Asia/Taipei，Gmail SMTP + healthchecks.io dead-man switch |
| 設定變更 | 改 `cluster.yaml` → `task configure` → commit → push。Flux 自行套用 |
| 模板漂移 | 定期 `./scripts/check-template-drift.py <cluster-repo>`。漂移是靜默的：不比對就不會有人發現某座叢集停止接收改進 |
| 強制同步 | `task reconcile` |

### 依維度分歧

| 條件 | 維運差異 |
|------|---------|
| `profile: appliance` | 異地備份是強制的，且 `age.key` **必須** escrow——備份加密到叢集自己的公鑰，金鑰在備份要對抗的那顆碟上 |
| `profile: full` / `prosumer` | 備份是選配。**目前三座 `full` 叢集都沒有**——選配的東西沒有人會主動去選 |
| `replicated_storage: true` | 移除遠比安裝麻煩，升級節點前先讀 [`replicated-storage.md`](../operations/replicated-storage.md) |
| 資料庫仍在 NFS | 失效模式是**靜默損毀**，唯一救援是備份。搬遷是 dump/restore，`storageClassName` immutable |
| `provisioning_path: talos` | `task talos:apply-node IP=<ip>` / `upgrade-node` / `upgrade-k8s` |
| `provisioning_path: omni` | 升級在 Omni UI 進行 |
| 多節點 + node-local | 失去任一節點就同時失去資料與重啟的能力 |

### 換 storage class 的順序（踩過坑）

先確認**叢集上**的 `DB_STORAGE_CLASS` 已是新值，再刪 PVC。push 不等於叢集知道：
cluster-secrets 是獨立的 Kustomization，有自己的節奏，而 PVC 重建幾乎是瞬間的——
jcom 就是在那個時間窗裡被 Flux 用舊值重建成 `sc-nas`，而那改不回來。見 `deployment-profiles` D38。

---

## 7. 目前還沒有寫下來的程序

誠實列出，因為「以為有」比「知道沒有」更危險：

| 缺口 | 歸屬 |
|------|------|
| appliance 交付的 operator runbook | `factory-agent`（0/61，尚未起頭） |
| 客戶 onboarding 溝通管道 | `zero-it-onboarding`（16/50） |
| 便宜路由器下的健檢做法 | `deployment-profiles` 5.7 / D45——**待決定** |
| 還原演練與還原程序文件 | `deployment-profiles` 8.3 / 8.4——備份的 restore 半邊從未被執行過 |
| genie1 遷移到 profile schema | `reconcile-jcom-lineage` 2b.5 |

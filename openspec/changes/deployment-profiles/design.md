## Context

這個 repo 交付的是**隱私驅動的地端叢集**：客戶之所以要這台機器，正是因為 homebridge、MQTT、IoT、存放公司知識的 PostgreSQL 這些東西不能放雲端。所以 LAN 可達性是產品需求，不是可以優化掉的實作細節——設計初期曾假設「ingress 全部走 Cloudflare Tunnel，LB IP 只是內部記帳」，這個假設在確認 `jg-base` 現況後作廢，本文件記錄修正後的方向。

現況（已查證）：

```
jg-base/kubernetes/apps/base/network/
  envoy-gateway/app/envoy.yaml:55   CLOUDFLARE_GATEWAY_ADDR   ← 只有叢集內 cloudflared 連
  envoy-gateway/app/envoy.yaml:85   CLUSTER_GATEWAY_ADDR      ← LAN 必須可達
  k8s-gateway/app/helmrelease.yaml:19  CLUSTER_DNS_GATEWAY_ADDR  ← LAN 必須可達
  cloudflare-dns  --gateway-name=envoy-external, policy: sync, txtPrefix: k8s.
jg-base/kubernetes/apps/extras/default/
  mqtt/app/tcp-gateway.yaml:10      MQTT_LB_IP                ← IoT 直連，LAN 必須可達
  homebridge/app/helmrelease.yaml:31  hostNetwork: true       ← 用節點 IP，不佔 LB IP
```

也就是：內網服務名稱目前**只存在於 `k8s-gateway` 的回答裡**，LAN 用戶端必須把 DNS 指向它才找得到。對零 IT 客戶而言這需要登入路由器改 DHCP option 6，是不可行的一步。

約束：
- 客戶端不可要求任何路由器設定、任何裝置設定。
- 既有叢集（jcom、jg-jiahd 等）必須能繼續運作，遷移成本要低且失敗要早。
- 不引入超出既有工具鏈（Cilium / external-dns / cert-manager / SOPS+age / Flux / daily-check）的新外部相依。

## Goals / Non-Goals

**Goals:**
- `appliance` profile 下，客戶必填欄位為 0；其餘由 factory agent 或渲染期推導。
- 消除「必須知道 LAN 上哪些 IP 空著」這個前置知識。
- 內網服務在**不改動客戶路由器與裝置**的前提下，於 LAN 上可用名稱存取。
- 把資料庫從 NFS 移到 block，並補上單節點必然缺少的備援。
- 既有 `full` 叢集行為不變，遷移只是補兩個宣告欄位。

**Non-Goals:**
- 不做 `factory-agent`（change ③）與 README 拆分（change ④），本 change 只鋪地基。
- 不實作 DHCP lease-holder，只保證介面可替換。
- 不處理 `revive-talos-path`（change ①）。
- 不為 appliance 提供高可用；appliance 明確是單節點，備份是它的容錯手段。
- 不改變 `extras:` 的語意與現有 extras 的行為。

## Decisions

### D1. 兩條正交軸，而非單一 profile 列舉

`deployment_profile`（客戶型態）與 `storage_backend`（儲存基礎設施）分開。理由：有 NAS 的客戶不見得要 `full` 的手動控制權，反之亦然。若壓成單一列舉，每新增一種組合就要多一個 profile 名稱。

*Alternative considered*：單一 `profile` 列舉含儲存語意。捨棄，因為組合會爆炸且語意混在一起。

### D2. `deployment_profile` 不給 schema 預設值

CUE 上不設 `*"full" | ...`。既有 `cluster.yaml` 會在 `cue vet` 階段直接失敗，而不是被預設值靜默套進某個 profile 後渲染出錯的東西。`task configure` 的流程是「validate → render → encrypt」，驗證失敗時 `kubernetes/` 不會被寫入，所以 fail fast 是安全的。

*Alternative considered*：預設 `full` 讓既有叢集零遷移。捨棄——靜默預設會讓「這台是哪種客戶」變成隱含知識，而這正是後續 factory agent 要據以決策的欄位。

### D3. LAN 位址不是「避開」，而是「壓到 1 個」

三個 LAN 可達服務的 port 完全不重疊（80/443、1883、53），可共用同一個位址。**已於 jg-jiahd（Cilium v1.19.1）實測確認**，見下方 spike 結論。

不需要 LAN 可達的兩個不是「搬到保留區段」，而是**直接不存在**：

- `cloudflare_gateway_addr`：cloudflared 的 config 指向 `https://envoy-external.network.svc.cluster.local:443`（`cloudflare-tunnel/app/helmrelease.yaml:80`），走 ClusterIP DNS。jg-jiahd 上 `envoy-external` 佔著 `10.9.9.5` 卻沒有任何東西連它。appliance 下 `envoy-external` 改 ClusterIP 即可。
- `cluster_api_addr`：Omni 自己 proxy，appliance 下不需要 LB 位址。

（初稿曾提議把這兩者放進固定的 `10.9.9.0/24` 保留區段。**已捨棄**——`10.9.9.0/24` 正是 jg-jiahd 自己的 node CIDR，拿一個自家在用的網段當「保證不撞」的保留區在語意上是錯的；而且既然兩者都不需要位址，保留區本身就是多餘的。）

「找 1 個空位址」與「找 4 個空位址」是不同難度的問題，這一步把後續探測的失敗率降一個數量級。

*Alternative considered*：全部走 Tunnel、不要 LAN 位址。**已作廢**——與地端隱私定位直接衝突，IoT 與 HomeKit 需要 L2 相鄰。
*Alternative considered*：把叢集放到獨立網段（雙網卡當路由器）。捨棄——appliance 會變成客戶網路的單點，重開機順序錯誤就整網斷線，對零 IT 是不可接受的失敗模式。
*Alternative considered*：改用 Envoy Gateway 的 `mergeGateways`，讓 internal gateway 與 tcp-gateway 共用一個 Envoy Service。捨棄——merge 的範圍是整個 GatewayClass，會把 `envoy-external` 一起併進來；要分開就得拆兩個 GatewayClass，比 sharing-key 重得多。

#### Spike 1.1 實測結論（jg-jiahd, Cilium v1.19.1, 2026-08-09）

測試以專用 pool（`192.0.2.0/29`, RFC 5737 TEST-NET-1）+ `serviceSelector` 隔離，兩個測試 Service 明確指定位址，全程未佔用任何真實 LAN 位址；production 的四個 LoadBalancer 位址在測試前後完全一致，測後資源已刪除無殘留。

| 驗證項 | 結果 |
|---|---|
| 跨 namespace 共用同一位址 | ✅ 兩個不同 namespace 的 Service 同時取得 `192.0.2.1` |
| `sharing-cross-namespace` 只掛單邊 | ✅ 失敗且**可觀測**：`cilium.io/IPAMRequestSatisfied=False`，reason `already_allocated_incompatible_service`，訊息 `different and not permitted namespace`；另一邊不受影響 |
| port 衝突（位址受約束時） | ✅ **不會**靜默多配位址：衝突方 unassigned，同樣回報 `IPAMRequestSatisfied=False`，訊息 `same port and protocol` |
| CRD 版本 | 叢集實際服務並儲存為 `cilium.io/v2`；`jg-base` 的 manifest 仍寫 `v2alpha1`（仍被接受，但應更新） |

關鍵推論：文件所述「port 衝突時多配一個 IP 進 sharing key 的集合」只適用於**自動配發且有多餘位址可拿**的情況。一旦位址被約束（明確指定，或 pool 只含單一位址），衝突就退化成 `IPAMRequestSatisfied=False` 這個乾淨的訊號——**收窄 pool 因此不只是精簡，它是把靜默失敗轉成可觀測失敗的執行機制**，而 `cilium.io/IPAMRequestSatisfied` 正好是 daily-check 可以監看的條件。

未於本次實測涵蓋（風險過高或超出範圍，移至 scratch 叢集驗證）：
- 服務同時匹配「窄 pool」與「涵蓋整個 node CIDR 的寬 pool」時的選擇順序。未測是因為若 Cilium 選了寬 pool，自動配發會取該區段第一個可用位址（`allowFirstLastIPs: "No"` 下即 `10.9.9.1`），那極可能是閘道器，會在真實 LAN 上造成 ARP 衝突。
- 單一位址 pool 下的自動配發是否落到 Pending（推論成立，但未實測）。
- Envoy Gateway 的 `spec.infrastructure.annotations` 是否會把 `sharing-key` 傳導到產生的 Service。本次測的是原生 Service。既有 production 已證實 `lbipam.cilium.io/ips` 經此路徑傳導成功，而傳導是通用的 annotation 複製，因此推論成立——但仍是推論。

### D3a. 現有 pool 涵蓋整個 node CIDR 是既有風險

`jg-base/kubernetes/apps/base/kube-system/cilium/app/networks.yaml` 的 pool 是 `cidr: ${NODE_CIDR}`，實測 jg-jiahd 即為 `10.9.9.0/24`。今天沒出事只因為每個 Service 都用 `lbipam.cilium.io/ips` 釘死位址；任何一個漏掉註記的 Service 都會從整個客戶 LAN 隨機取一個位址並經 L2 announcement 宣告，可能與真實裝置衝突。

本 change 收窄 pool 同時修掉這個既有風險。對 `full` profile 是行為改變（需明確列出該叢集實際使用的位址），必須逐叢集確認後再套用。

### D4. 先 ARP 探測，介面預留 DHCP lease-holder

ARP 探測只能證明「此刻沒人用」，證明不了「不在 DHCP pool 內」——當下關機的裝置回來就會撞號。根治做法是讓路由器自己配（合成 MAC 發 DHCPDISCOVER/REQUEST 並持續續租），但那是新元件。

折衷：先做探測，但把唯一對外契約定義為產出 `CiliumLoadBalancerIPPool`。之後替換實作不需動 Cilium 設定、Service 註記、模板或 CUE。撞號則靠持續監看 + 併入日常健檢回報，不假裝不會發生。

### D5. hostname 維持扁平，不引入 `.lan.`

內外之分已由 HTTPRoute 的 `parentRefs` 表達，那是 operator 看的地方。放進 URL 等於放進使用者看的地方，而使用者是搬遷成本的承受方：書籤、IoT/MQTT broker 位址、HomeKit 配對、Auth0 Allowed Callback URLs（`cluster.sample.yaml` 已逐 instance 記錄）、憑證 SAN 全都要改，而且服務在內外之間搬動會從「改一行 `parentRefs`」變成 breaking change。

關鍵觀察：**沒有名字衝突需要解**。每個 hostname 只會掛在一個 gateway 上，不會同時需要內外兩種答案，所以扁平名稱直接發公開 A 記錄即可。

*Alternative considered*：`app.lan.<domain>`。捨棄，理由如上。

### D6. 內網名稱走公開 DNS 的不 proxy A 記錄，`k8s-gateway` 降為 fallback

新增第二份 external-dns（`--gateway-name=envoy-internal`），把內網 route 發成指向 LAN 共用位址的 A 記錄，且必須關閉 proxy（Cloudflare 無法 proxy RFC1918）。LAN 用戶端用路由器給的任何 resolver 都能解出來，**不需要動路由器、不需要動裝置**。

兩份 external-dns 都是 `policy: sync` 且同一個 zone，因此 `txtPrefix` 與 `txtOwnerId` 必須分離，否則會互刪對方記錄——這是本設計最容易踩的實作陷阱。

`k8s-gateway` 不砍，改為偵測到 DNS rebinding protection 後才啟用。因為名稱扁平，啟用時回答的是同一組名稱、同一個位址，**切換不需要任何客戶端變更**，兩種模式可雙向移動。

揭露面：cert-manager 簽發的每個 hostname 本來就會進 Certificate Transparency log，所以發佈內網名稱不構成新的洩漏；回的是 RFC1918，外部解得到但連不到。

### D7. 資料庫走 block，拒絕 NAS-Docker 逃生梯作為預設

PostgreSQL 跑在 NFS 在 fsync 與鎖語意上本來就不該做，改 local-path 是修正而非妥協。容量真的不足時的正解是**更大的本機 NVMe**，或以 CSI 提供 NAS 的 block（iSCSI），而不是把 DB 搬到 NAS 上的 Docker。

搬到 NAS Docker 的代價不在效能，在於它**離開受管邊界**：不在 Flux、agent 管不動、daily-check 看不到、交接封裝涵蓋不到——而 DB 恰好是最不能出事的東西。它可以是明示的逃生梯，但必須標註「這一塊不在受管範圍」。

同時修正 `jg-base/kubernetes/apps/extras/default/postgres/app/backup.yaml:13,26` 的 `storageClassName: ""`（關閉動態供裝，在無預建 PV 的 appliance 上會永久 Pending）。

### D8. agent 工作區與 agent 記憶分層

工作區檔案可重建，放 local-path 即可。agent 累積的每客戶 context 不可重建，放進資料庫層，因而自動被備份涵蓋。`nas_coding_path` 保留為 optional（jcom / jg-jiahd 仍在用），不移除。

### D9. 備份重用既有零件

`pg_dump` + 工作區 → 以叢集 age 公鑰加密 → Cloudflare R2（每叢集本來就有 CF 帳號，S3 相容，免費額度足夠）。新鮮度由既有的 `monitoring/daily-check` 一併回報，斷了就經由既有的 healthchecks.io dead-man switch 浮上來。整條鏈沒有新的外部相依。

以叢集自己的公鑰加密，代表 R2 上的內容連 operator 也解不開，符合隱私定位；解密能力隨 `age.key` 移轉，天然接上 `task handover`。

### D10. `appliance` 僅限 Omni

手動 Talos 需要每節點的 IP、網卡與磁碟選擇器，零 IT 客戶給不出來。這個組合在驗證期就拒絕，而不是等到 bootstrap 才失敗。

### D11. Base app 的 gating 由 per-user repo 生成 suspend patch

`jg-base` 把每個 base app 無條件列在 `apps/base/*/kustomization.yaml` 裡，**Flux 無法從那一端拒絕建立 Kustomization**。所以「這個 profile 不要這個 base app」只能從 per-user repo 表達。

機制沿用 jcom 已驗證可行的作法：在 `cluster-apps-base` 的 patches 內對子 Kustomization 設 `suspend: true`。差別在**來源**——jcom 是手寫進 `ks.yaml.j2`，這裡是**由 `cluster.yaml` 推導生成**。同樣的 YAML，但一個是漂移、一個是宣告式設定，正好是 `reconcile-jcom-lineage` 的 `per-cluster-override-contract` 要求的分野。

patch 刻意只設 `suspend` 這一個純量欄位。jcom 的註解記錄過原因：**第二個 strategic merge 若設了 `spec.patches` 會整個取代該列表**，把上面通用的 HelmRelease 策略 patch 靜默吃掉。

目前 gating 兩項：

```
nfs-client-provisioner   storage_backend != 'nfs'
spegel                   is_single_node
```

#### 為什麼不是「從 extras 過濾」

初版實作誤以為 `storage/nfs-subdir` 是 extra，於是在 extras 迴圈裡把它濾掉——但它在 jg-base 是 **base app**（`apps/base/storage/nfs-subdir/ks.yaml`），從來不在 extras 裡。過濾器濾了一個不存在的東西，而當初的測試用一份「把它塞進 extras」的設定，於是測過了卻測錯對象。2026-08-11 在真實叢集上才發現：`local-path` 叢集照樣部署它並失敗，錯誤訊息精確指出原因——`NAS_SERVER` / `NAS_PATH` 被渲染為空字串，Deployment 因 `nfs.server: Required value` 建不起來。

#### suspend 不會清理既有資源

實測確認的語意：`suspend: true` 讓 Flux **停止 reconcile**，但**不會移除已部署的資源**。在測試叢集上 suspend 生效後 spegel pod 仍在跑；手動刪除 HelmRelease 之後，Flux 兩分鐘內沒有重建。

所以：
- **新叢集**：suspend 從第一次同步就在，該元件從未被部署。
- **既有叢集**：suspend 只防止重建，已部署的要手動刪除。

jcom 的註解其實早就寫了這件事（「stops reconciling/**recreating** it」），只是把它當成既定知識而非遷移步驟。

#### 既有叢集的遷移步驟（2026-08-11 於 jgt-omni 實測）

先看清楚 suspend 之後留下了什麼。以 `nfs-client-provisioner` 為例，它的 inventory 是 HelmRelease + HelmRepository，但 helm 另外建了 ServiceAccount 與 **StorageClass `sc-nas`，而且是叢集的 default** ——一台 `local-path` 叢集的預設儲存指向一個不能用的 NFS provisioner，這比「一個 pod 失敗」嚴重得多。

**刪除被 suspend 的 Kustomization 不會清理資源。** 實測：刪掉之後 HelmRelease 與 StorageClass 都還在，`prune: true` 沒有生效——suspend 擋掉了刪除時的 prune finalizer。所以這條路是無效的，而且它看起來像成功（Kustomization 確實消失了）。

有效的做法是**直接刪除 HelmRelease**，讓 helm-controller 執行 uninstall：

```
kubectl -n <ns> delete hr <release>     → helm uninstall 連帶清掉它建立的
                                          StorageClass / ServiceAccount 等
```

驗證結果：

```
刪 Kustomization        → hr 仍在、sc 仍在      ✗ 無效
刪 HelmRelease          → hr=0、sc=0            ✓ helm uninstall 清乾淨
強制 cluster-apps-base   → Kustomization 重建
reconcile                  但 suspend=true 守住，hr=0 sc=0 維持 ✓
```

最後一列是關鍵：`cluster-apps-base` 會把子 Kustomization 重新建出來（它自己沒有被 suspend），但重建出來的帶著 suspend patch，所以不會重新部署。順序因此是 **先刪資源、再讓 suspend 擋住重建**，而不是反過來。

（另注意 `cluster-apps-base` 的 interval 是 1h，所以刪掉子 Kustomization 之後不會立刻重建——實測 100 秒內都沒有動靜。除錯時容易誤判為「已經永久移除」。）

### D12. Omni 路徑無法在渲染期得知節點數

`is_single_node` 在 appliance（定義上單節點）與手動路徑（節點清單具權威性）可以推導，但 Omni 叢集的 `nodes` 恆為 `[]`。新增可選欄位 `single_node`，明寫者優先；未宣告時**假設有 peer**——猜錯只是多跑一個本來能用的元件，反向猜錯則會靜默停掉需要的元件。

### D13. `storage_backend` 的兩個值蓋不住三種情境

`local-path` 把兩個後果完全不同的情境混成同一個值：

| | local-path 是否適當 |
|---|---|
| 單節點無 NAS | ✓ 正確且完整 |
| **多節點無 NAS** | ⚠ 可用但降級——正解是複製式儲存 |

node-local 的 PV 帶著指向該節點的 affinity。多節點上這會**在第一次排程時**把每個有狀態工作負載悄悄釘死在一台機器：pod 排不到別台、那台碟壞了資料與服務一起沒。表面上有三個節點，實際上 postgres 只活在其中一台。

`cluster-storage-tiers` 原本只要求「DB 用 block-backed storage」，而 `local-path` 技術上就是 block-backed——多節點叢集選它會**通過所有檢查**，直到某次節點維護才發現起不來。spec 缺的是「block-backed 但不可跨節點漂移」這個維度。

正解是 Longhorn / Rook-Ceph 這類複製式 block storage。README Stage 1 提過它們，但 **jg-base 完全沒有實作**（只有 nfs-subdir 與 local-path-provisioner）。實作一整套複製式儲存範圍不小，因此分兩步：

- **現在**：CUE 拒絕「`local-path` + 多節點」除非明寫 `accept_node_pinning: true`。把沉默的降級變成明示的選擇。
- **之後**：在 jg-base 實作複製式儲存並加入第三個 `storage_backend` 值。jg-jiahd 是 3 節點，所以這不是假想需求。

#### 實作上的一個 CUE 陷阱

要求「使用者必須明寫某個值」比看起來難。三次嘗試都被 CUE 自己滿足了：

```
accept_node_pinning: true          → CUE 直接賦值，永遠通過
_hidden: accept_node_pinning & true → hidden field 不受 concreteness 檢查
accept_node_pinning?: "字面值"       → 引用時取到具體的字面值，仍然通過
```

有效的是**讓宣告的約束保持非具體**，再用矛盾拒絕不要的值：

```cue
accept_node_pinning?: bool          // 非具體
if single_node == false {
    accept_node_pinning: bool       // 缺值 → incomplete → 拒絕
    if accept_node_pinning == false {
        accept_node_pinning: _|_    // false → 矛盾 → 拒絕
    }
}
```

通則是：**`cue vet` 檢查的是「資料是否具體」，所以任何在 schema 裡寫死的值都會讓要求自我滿足**。

### D14. `local-path` 路徑上，claude-code 有一整條未被走過的 NFS 假設鏈

2026-08-11 在 jgt-omni（單節點、無 NAS）第一次真的把預設 instance `im` 跑起來，中間撞到五道牆。它們不是五個獨立 bug，是**同一個假設的五個位置**：claude-code 是在有 NAS 的叢集上長出來的，所以「有 NFS」被寫死在各處。

| # | 位置 | 症狀 | 修法 |
|---|---|---|---|
| 1 | `helmrelease.yaml.j2` 的 `coding` volume 硬寫 `type: nfs` | `server`/`path` 渲染成空字串 → chart schema 直接拒絕，**整個 release 裝不起來**（不只是少一個掛載） | 用 `nas_coding_path` 包起來 |
| 2 | 兩個 PVC 硬寫 `storageClass: sc-nas` | 該 class 在 local-path 叢集不存在 → PVC 永遠 Pending | 改用 `default_storage_class` |
| 3 | 沒有任何 default StorageClass | `storage/local-path-provisioner` 是 opt-in extra（見 2c.6） | `ks.yaml.j2` 依 `storage_backend` 自動加入 |
| 4 | `replicas: 0` × `WaitForFirstConsumer` | Helm 等 PVC 綁定，但沒有 pod 就不會綁 → 逾時後 release 永久失敗 | `install`/`upgrade` 加 `disableWait: true` |
| 5 | `storage` namespace 無 PodSecurity 標籤 | Talos 預設 `baseline` 擋掉 provisioner 的 hostPath helper pod | jg-base `05b1501`：標為 `privileged` |

兩個值得單獨記住的：

**#4 是兩個各自正確的決定相撞。** `replicas: 0` 是刻意的安全姿態（不常駐一個 root shell），`WaitForFirstConsumer` 是 node-local 儲存的正常行為——延後綁定才知道要綁哪台。湊在一起就是「Helm 等一個依定義不會發生的事件」。NFS 用 `Immediate` 綁定，所以**這個相撞在有 NAS 的叢集上完全不會出現**。

**#5 屬於「每個元件看起來都對」的那類故障。** provisioner pod `1/1 Running`、Kustomization `Ready=True`、StorageClass 存在——但 PVC 永遠 Pending，因為失敗發生在一個短命的 helper pod 上，錯誤只留在 PVC 的 event 裡：

```
failed to provision volume with StorageClass "local-path":
  pods "helper-pod-create-pvc-…" is forbidden:
  violates PodSecurity "baseline:latest": hostPath volumes (volume "data")
```

**通則**：這五道全部只在 `storage_backend: local-path` 上出現，也就是 **appliance profile 的標準組態**。有 NAS 的叢集一道都碰不到——所以這條路徑在此之前從未被端到端走過。②（以及後續每個 profile）的驗收必須包含**在目標 profile 上實跑**，不能只驗 `task configure` 的輸出：前四道在渲染階段全部無聲通過。

### D15. `storage_backend` 在回答兩個問題，只有一個是單值的

`local-path-provisioner` 原本是 extra，語意上被當成「NFS 的替代方案」——於是有 NAS 的叢集**不會裝它**。但它不是替代方案，是 node-local 那一層：D7 要求 PostgreSQL 離開 NFS（fsync 與鎖語意，與 NAS 多大無關），而在 `storage_backend: nfs` 的叢集上，DB 無處可去。Group 6.4 因此在 jg-jiahd 上根本無法實作。

```
「裝哪些 provisioner?」  → 常常兩個都要
「哪一張是預設 class?」  → 恰好一個
```

只有第二個是單值選擇。2026-08-11 起：`local-path-provisioner` 移入 jg-base base apps 且**永不 suspend**；`nfs-subdir` 維持 base 但無 NAS 時 suspend；`storage_backend` 只決定預設。`ks.yaml.j2` 那段 auto-add 隨之刪除——它存在的唯一理由就是「是 extra 但又非裝不可」，這個矛盾本身就是訊號。

**連帶要修的 predicate**：D13 的 `accept_node_pinning` 閘門掛在 `storage_backend == 'local-path'`。local-path 現在到處都在，6.4 又要把 DB 放上去，於是 jg-jiahd（3 節點、NFS）會把 postgres 釘死在一台**而閘門不觸發**。該問的是「有沒有工作負載落在 node-local class」，不是「local-path 是不是預設」。列為 Group 6 的前置。

### D16. 遷移 runbook 從未被執行過，而它是錯的

jg-base README 那份「suspend 母 Kustomization → `kubectl patch spec.prune=false`」的步驟，是 2026-08-08 jcom 掉 PVC 之後寫下的**補救建議**，沒有人跑過。2026-08-11 第一次照著跑（local-path 遷移），release 照樣被 uninstall。兩個各自獨立的原因：

**一、`prune` 不是管刪除串聯的欄位。** CRD 寫得很清楚：

> `deletionPolicy` … Valid values are (`MirrorPrune`, `Delete`, `WaitForTermination`, `Orphan`). **`MirrorPrune` mirrors the Prune field**. Defaults to `MirrorPrune`.

`prune` 只透過 `MirrorPrune` 才會被讀到。而本模板生成的每個 Kustomization 都**明寫** `deletionPolicy: WaitForTermination`，所以刪除時 `prune` 根本不在路徑上。patch 下去讀回來一模一樣，看起來完全成功。

**二、線上 patch 本來就留不住。** 兩個欄位都宣告在 git 裡，母 Kustomization 下次 server-side apply 就覆蓋回去。想靠 suspend 母體擋住也不行：suspend 當下看是生效的，但已在飛行中的 reconcile 照樣落地，而且這個 stack 的 `Kustomization/flux-system` 帶著 `app.kubernetes.io/managed-by: flux-operator`——另一個 controller 對它的 spec 有自己的主張。

有效做法是**走 git，分兩次 push**：先把退役的 Kustomization 設成 `deletionPolicy: Orphan`、確認真的 apply 了，再 push 移除。

這次選在 jgt-omni 上試是對的：local-path 的 PV 是節點上的 hostPath，helm uninstall 拿走 StorageClass 與 Deployment，但**不碰還有 PVC 綁著的 PV**。兩個 PVC 全程 Bound，復原只需要一次 `flux reconcile source git jg-base`。同一個錯誤發生在 claude-code 的 PVC 上就是 jcom 那次的資料損失。

**通則**：一份沒被執行過的 runbook 不是文件，是假設。而它會在最壞的時刻被照著執行——上一次就是。

### D17. 儲存分層有三層，不是兩層

Group 6 實作後定形為三個名稱，各自回答不同問題：

| 變數 | 值 | 誰用 |
|---|---|---|
| `DEFAULT_STORAGE_CLASS` | `storage_backend` 決定 | 沒指定 class 的 PVC、bulk 資料 |
| `DB_STORAGE_CLASS` | **恆為 block tier**，與 `storage_backend` 無關 | 需要 fsync 與檔案鎖的（D7） |
| `LOCAL_PATH_IS_DEFAULT` | `storage_backend != nfs` | local-path 是否宣告自己是叢集預設 |

第三個是補一個真正的洞：`nfs-subdir` 寫死 `defaultClass: true`，但它在無 NAS 的叢集上被 suspend，而 local-path 從來沒宣告過——於是那種叢集**一張 default class 都沒有**，任何省略 `storageClassName` 的 PVC 都會 Pending 指著空氣。兩者永不相撞，因為 `LOCAL_PATH_IS_DEFAULT` 為真的條件恰好就是 nfs-subdir 沒在跑。

`default/postgres` 的 PVC 原本**完全沒寫 class**——於是在 NFS 叢集上，資料目錄靜默落在 `sc-nas`。D7 早就寫著不該這樣，但沒有任何東西在檢查，因為「沒寫」看起來不像一個選擇。

#### 預設值刻意選了「錯的那個」

`${DB_STORAGE_CLASS:=sc-nas}` 的預設不是正確答案，是**現狀**。理由是 PVC 的 `storageClassName` immutable：預設值只在 cluster-secrets 沒有該鍵時生效，也就是還沒遷移到 profile schema 的叢集，而那些全是 DB 已經在 NFS 上的 NFS 叢集。若預設成正確的 block tier，下一次 reconcile 會拿一個改不動的欄位去 patch 活的 PVC，把 jg-jiahd 與 jcom 的 Flux 打成永久紅燈——而資料一步也沒搬。

真正的搬遷是 dump → 刪 PVC → 用 block class 重建 → restore，那是 6.7，per-cluster 的動作。`db_storage_class` 欄位的作用是讓「還沒搬」變成 `cluster.yaml` 裡看得見的一行。

同樣的 immutable 顧慮讓 `server: 10.9.2.13` → `${NAS_SERVER}` 這個改動必須先查證：PV 的 `nfs.server` 也是 immutable，只有在唯一啟用那些 extras 的叢集上兩者解析為同一位址，才推得下去。查證過了，是同一個。

### D18. 「掃出一個缺陷」與「掃出的是那個缺陷」是兩回事

6.1/6.2 原本寫的是「修掉 `storageClassName: \"\"`，它會讓 PVC 永遠 Pending」，spec 甚至有一條需求叫「No PVC depends on manual pre-provisioning」。實際打開 13 處來看，**每一處都是同一份 manifest 裡的 PV/PVC 靜態配對，用 `volumeName` 綁定**——既有 NFS export 的正確用法，會立刻 Bound。

原始診斷是在沒讀檔案的情況下下的：看到 `storageClassName: ""` 就套用了那個 pattern 最常見的解釋。掃描本身是對的，它確實掃出了缺陷——只是缺陷是**寫死的 NAS 位址**，不是空字串。

若照原需求執行，會把四組正常運作的靜態綁定改成動態供裝，在 jg-jiahd 上把 linebot 的知識庫與 synophoto 的 vault 從既有 NFS export 換成新配的空目錄。**照著錯的規格做，比不做更糟**——spec 已改寫，並保留原文與被推翻的過程。

### D19. 延後搬遷是有代價的選擇，代價要當場付掉

6.7 的決定是**不搬**：jg-jiahd 的 postgres 留在 `sc-nas`，等 2c.8 的複製式儲存。理由站得住腳——搬到 local-path 是拿「可跨節點重新排程」換「正確的 fsync/鎖語意」，而 2c.8 兩者都給，何必先付一次遷移成本再付第二次。

但這個選擇有個立即的後果：**jg-jiahd 的資料庫繼續待在 NFS 上，而 postgres on NFS 的失效模式是靜默損毀**——不是崩潰，是某天發現資料不對。那條路徑的唯一救援是每天那份 dump。

而那份 dump 的 **restore 半邊從未被執行過**。備份 CronJob 每天寫出 48 KB 的檔案、留 14 份、job 全部 Completed——證明的是「dump 會產生檔案」，不是「檔案能還原成資料庫」。這正是 D16 那個錯誤的形狀：一份沒被執行過的程序不是保障，是假設。

所以延後搬遷的同時就把演練做掉了。在 jg-jiahd 起一個拋棄式 postgres、唯讀掛上備份卷、還原 `linebot-20260810.sql.gz`：

```
prod                    restored
episodes=148            episodes=148
knowledge=34            knowledge=34
line_user_projects=29   line_user_projects=29
line_users=29           line_users=29
projects=7              projects=7
schema_migrations=13    schema_migrations=13
sites=3                 sites=3
task_confirmations=11   task_confirmations=11
trello_boards=20        trello_boards=20
working_memory=11       working_memory=11
```

逐表相同，0 error。同時查出一個**前置條件**：必須先 `create role linebot`，否則 dump 裡每一句 `OWNER TO linebot` 都失敗——表還是會建起來，資料也在，但擁有者變成 `postgres`。這種「看起來成功了」的還原，正是會在真正需要的那天才發現不對的東西。

**通則**：接受一個風險的時候，同時驗證對應的補償措施還活著。否則「我們有備份」和「我們有 runbook」是同一種話。

### D20. 決定會反過來證偽 schema

`accept_node_pinning` 的 predicate 在一天之內錯了兩次，兩次都是同一種錯——問的是代理指標，不是實際狀態：

```
v1  storage_backend == "local-path"              漏掉：有 NAS 但 DB 在 block tier 的叢集
v2  ... 或 有 block-tier extra                    誤抓：明寫 db_storage_class 把 DB 移開的叢集
v3  ... 或 (db_storage_class 是 node-local 且 有 block-tier extra)
```

v2 是為了修 v1 而寫的，寫的時候看起來完備。**是 6.7 的決定把它證偽的**：使用者選「不搬、明寫 `sc-nas`」，我去套用時才發現 schema 會要求 jg-jiahd 承認一件在它身上不會發生的事——DB 明明在 NFS 上，卻被要求簽署 node-pinning 同意書。

一個要求使用者承認風險的閘門，如果會對沒有該風險的人發問，它教出來的行為就是「照簽」。那比不問更糟——D13 花了三次嘗試才讓 CUE 無法代簽，結果 predicate 本身讓簽名失去意義。

**通則**：實際去用一次 schema，比再讀一遍 schema 有效。這兩次修正都不是想出來的，是套用到真實叢集時撞出來的。

## Risks / Trade-offs

- ~~**Cilium `sharing-key` 跨 namespace 未經驗證**~~ → **已於 2026-08-09 在 jg-jiahd 實測確認可行**（見 D3 的 spike 結論）。內網位址數確定為 1。
- **收窄 pool 對既有叢集是行為改變** → `full` profile 需逐叢集列出實際使用位址後再套用；未列全會讓某個 Service 失去位址，但因為會回報 `IPAMRequestSatisfied=False`，屬可觀測失敗而非靜默中斷。
- **`envoy-external` 改 ClusterIP 對既有叢集是行為改變** → 若有人習慣從 LAN 直接打該位址（而非經 Cloudflare），會斷。僅在 `appliance` 下預設改變，`full` 維持現狀。
- **ARP 探測撞號無法根治** → 持續監看 + 併入日常健檢 + 撞號時自動改選並記錄新舊位址；長期以 DHCP lease-holder 取代，介面已預留。
- **DNS rebinding protection 會擋掉公開 A 記錄回私有 IP**（Fritz!Box、部分 ASUS、pfSense 預設） → 開機自檢偵測後啟用 `k8s-gateway` fallback；因名稱扁平，切換零遷移。
- **local-path 讓 pod 綁死單一節點** → appliance 本就是單節點，語意一致；`prosumer`/`full` 多節點叢集若把 DB 放 local-path，需明確接受該 pod 不可跨節點漂移。
- **BREAKING：既有 cluster.yaml 需補兩個欄位** → 失敗發生在 `cue vet`、渲染之前，不會產出半套設定；遷移是每個 repo 加兩行。
- **單碟切兩個分割不防磁碟故障** → 因此 appliance 的離線備份是強制而非選配；分割只解決系統與資料互相踩踏。
- **備份鏈依賴 Cloudflare R2** → 若 R2 不可用，備份中斷會經由 daily-check 的 dead-man switch 曝光，不會靜默失敗。
- **`age.key` 是單點** → escrow 為強制項，且列為交接封裝第一項；未 escrow 即視為 provisioning 未完成。

## Migration Plan

1. **先讓既有叢集無痛**：schema 加入兩條軸後，jcom / jg-jiahd 等各補 `deployment_profile: full` + `storage_backend: nfs`，行為與今日完全相同，先確認 `task configure` 綠燈。
2. **jg-base 側加法優先**：第二份 external-dns、備份 CronJob、LAN 位址探測元件都是新增資源，不影響既有叢集（它們仍走 `k8s-gateway`）。
3. **postgres 儲存層與 backup PVC 修正**：對既有叢集是資料搬遷，需個別排程，不隨 profile 上線一起做。
4. **appliance 首台以 scratch 叢集驗證**，還原演練通過後才用於真實客戶。
5. **Rollback**：本 change 的每一項在 `full` profile 下皆為 no-op 或加法，回退方式是把 profile 維持 `full` 並停用新增的 external-dns 實例與備份 CronJob。

## Open Questions

- ~~Cilium LB-IPAM 的 `sharing-key` 是否支援跨 namespace 共用？~~ **已解決**：支援，內網位址數為 1（Cilium v1.19.1 實測）。
- 服務同時匹配窄 pool 與寬 pool 時，Cilium 依什麼順序選擇？影響遷移期間兩種 pool 並存的安全性。須在 scratch 叢集驗證，不可在有真實裝置的 LAN 上測。
- DNS rebinding protection 的可靠偵測方式為何？從叢集內解析拿不到答案，必須從 LAN 上的用戶端視角測——是靠客戶手機（change ④ 的 LINE bot）回報，還是節點自己以 hostNetwork 查詢路由器指定的 resolver？
- Cloudflare DNS 對 RFC1918 A 記錄的實際行為（僅確認可 DNS-only，需實測是否有額外限制）。
- R2 的 bucket 與憑證由誰建立、放在哪一層設定？取決於 change ③ 對「每叢集 Cloudflare 帳號」的最終結論。
- `prosumer` 的預設 storage class 若為 NFS，DB 的 block 要求如何表達——是強制每個 DB PVC 明寫 class，還是另設一個永遠 block 的次要 class？

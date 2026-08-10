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

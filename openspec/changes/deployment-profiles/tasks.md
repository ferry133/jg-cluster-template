## 1. Spikes（先做，結果會改變後面的設計）

- [x] 1.1 驗證 Cilium LB-IPAM `lbipam.cilium.io/sharing-key` 跨 namespace 支援 — 2026-08-09 於 jg-jiahd (v1.19.1) 實測，可行；結論見 `design.md` D3
- [x] 1.2 內網共用位址數量確定為 1，已回寫 `design.md` D3/D3a 與 `specs/lan-address-allocation/spec.md`
- [ ] 1.3 實測 Cloudflare DNS 接受 RFC1918 A 記錄的行為（DNS-only 可行、proxied 應失敗），記錄實際錯誤訊息
- [ ] 1.4 決定 DNS rebinding protection 的偵測方式（節點 hostNetwork 查詢路由器 resolver vs 客戶端回報），回寫 `design.md` Open Questions
- [x] 1.0 appliance 是單節點，而 `jg-base/.../kube-system/kustomization.yaml:12` **無條件**部署 Spegel。**2026-08-10 已在測試機重現**：pod 永遠 `0/1`（`routing table is empty after bootstrapping`——單節點無 peer），且仍寫入 `_default/hosts.toml` 把所有 registry 導向本機死埠。惟 **image 拉取未受影響**（containerd 2.2.6 於 200ms 逾時後回退上游成功），故 jcom 記錄的「全叢集拉不動」應為舊 containerd 2.1.6 的行為。profile 仍須關掉 Spegel，但非緊急。**已由 2.8 的 suspend patch 處理**，並於 jgt-omni（單節點）確認 `suspend=true` 且 pod 已清除。詳見 `docs/template-lineage.md`
- [x] 1.5 **寬 pool 恆勝，規則是「建立時間最早者勝」**（2026-08-11，jgt-omni，Cilium v1.19.1）。窄 pool 只有在寬 pool `disabled: true` 時才被使用，證明它可用、只是不被選。三次實驗排除了另兩個假說：不是字典序（`aaa-spike-narrow` 輸給 `spike-wide`），也不是「最具體者勝」。
  - **直接後果**：不能在既有 `pool` 旁邊「加一個窄 pool」期待它被優先——jg-base 的 `pool` 在每個叢集上都是最早建立的，永遠贏。**4.6 必須收窄既有 pool，不能新增。**
  - **附帶確認 D3a（含一次自我更正）**：初測我的 spike pool 漏寫 `allowFirstLastIPs`（未指定＝可配發），拿到網路位址 `192.0.2.0`，我一度據此把風險上調；那是量到自己的設定。jg-base 明寫 `allowFirstLastIPs: "No"`，照抄補測後第一個配發是 `.1`。**D3a 原本的敘述就是對的**：第一個自動配發的 LB IP 就是預設閘道 `10.9.1.1`，且 `l2-policy` 的 `loadBalancerIPs: true` 無 serviceSelector，會直接 ARP 廣播出去。目前沒出事，只因三個現有服務都用 `lbipam.cilium.io/ips` 釘死位址，自動配發從未發生
- [x] 1.6 **確認**：單一位址 pool + 相同 `sharing-key`，port 不衝突者共用同一位址（`s1:80` 與 `s2:8080` 同得 `203.0.113.50`）；port 衝突者**拿不到位址**，並回報 `cilium.io/IPAMRequestSatisfied = False`。
  - **但 reason 是誤導的**：`reason=out_of_ips`，訊息為 *All enabled CiliumLoadBalancerIPPools that match this service ran out of allocatable IPs*——實際原因是共用位址上的 port 相撞，不是位址用盡。4.9 讓 daily-check 監看這個條件是對的（失敗可觀測），但**告警內容會把維運者指向錯誤的方向**，需要在告警文案裡點出「單一位址 profile 下，這通常代表 port 衝突」
- [x] 1.7 **確認，且比要求的更多**：`spec.infrastructure.annotations` 與 `spec.infrastructure.labels` **都**逐字傳到產生的 Service。labels 會傳這點是必要的——pool 的 `serviceSelector` 只能選 Service，而產生的 Service 預設只有 Envoy Gateway 自己的標籤，沒有 labels 傳導就無法讓它落進指定 pool。
  - 功能面也驗過（不只是「註解有出現」）：單一位址 pool 下，ns `spike` 的 Gateway（:80）與 ns `default` 的普通 Service（:9090）帶同一組 `sharing-key: gwshare` + `sharing-cross-namespace: "*"`，兩者同得 `203.0.113.90`，皆 `IPAMRequestSatisfied=True`。跨 namespace 共用經由 Gateway 傳導的 key 成立
  - 現網佐證：`envoy-internal` 的 `spec.infrastructure.annotations` 已帶 `lbipam.cilium.io/ips: 10.9.1.241`，產生的 Service 上原樣存在且生效

## 2. CUE schema 與範本（jg-cluster-template）

- [x] 2.1 `cluster.schema.cue` 加入 `deployment_profile`（三值、無預設）與 `storage_backend`（兩值）
- [x] 2.2 `nas_server` / `nas_path` 改為 `storage_backend: nfs` 時才必填；`nas_coding_path` 維持 optional
- [x] 2.3 appliance 下 `cluster_api_addr` / `cloudflare_gateway_addr` **不存在**（非「固定 10.9.9.x」——design D3 已改：cloudflared 走 ClusterIP DNS、API 走 Omni proxy，兩者都不需要位址）；`prosumer`/`full` 維持必填與互斥檢查
- [x] 2.4 appliance 下誤填 `cluster_gateway_addr` / `cluster_dns_gateway_addr` / `mqtt_lb_ip` 一律拒絕（看起來像設定了什麼、實際無人讀取）
- [x] 2.5 appliance ⇒ `provisioning_path: "omni"`（手動 Talos 需要零 IT 客戶給不出的節點資訊）
- [x] 2.6 新增 `backup_r2_*` 四欄位；appliance 下必填（單節點本機碟無備援，不該渲染出資料無保護的叢集）
- [x] 2.7 `plugin.py` 衍生 `default_storage_class`（nfs→sc-nas / 否則 local-path）與 `is_single_node`（appliance 恆真；talos 依節點數；其他 Omni 叢集無從判定故為 false）
- [x] 2.8 base app 依 profile gating（**非** extras 過濾——初版誤判 `storage/nfs-subdir` 為 extra，2026-08-11 實測發現）：`ks.yaml.j2` 由 `cluster.yaml` 生成 `suspend: true` patch，目前涵蓋 `nfs-client-provisioner`（非 nfs backend）與 `spegel`（單節點）。詳見 `design.md` D11
- [x] 2.9 `cluster-secrets.sops.yaml.j2` 加入 `BACKUP_R2_*`；並為改成 optional 的位址與 NAS 欄位補上顯式 `default()`（原本無防護，makejinja 的 chainable-undefined 會靜默渲染成空字串）
- [x] 2.10 `cluster.sample.yaml` 重組：新增 §0 Profile 置頂，標註 `(appliance: n/a)` 的欄位，NAS 改為條件必填，新增備份區塊
- [x] 2.11 三個 profile 各跑一次完整 `task configure` 皆通過，輸出符合預期（appliance 位址空/備份有值/extras 被過濾；full 位址與 NAS 齊全；prosumer+talos 的 coredns 推導為 10.43.0.10）

## 2c. 實測揭露的缺口（2026-08-11，jgt-omni 叢集）

- [x] 2c.1 已實作並在活叢集驗證：suspend patch 生成正確、Flux 已套用（`suspend=true`）、刪除後兩分鐘內未重建。`local-path` 叢集的失敗原因已精確佐證——`NAS_SERVER`/`NAS_PATH` 為空導致 Deployment `nfs.server: Required value`
- [x] 2c.4 新增可選欄位 `single_node`（Omni 路徑渲染期無法得知節點數，`nodes` 恆為 `[]`）；未宣告時假設有 peer——猜錯只是多跑一個能用的元件，反向猜錯會靜默停掉需要的
- [x] 2c.5 遷移步驟已在 jgt-omni 實測確立：**刪除被 suspend 的 Kustomization 無效**（prune finalizer 被 suspend 擋住，資源全留）；有效做法是直接 `kubectl delete hr`，helm uninstall 會連帶清掉它建立的 StorageClass / ServiceAccount。之後 `cluster-apps-base` 重建子 Kustomization 時 suspend 守住，資源維持消失。順序必須是「先刪資源、再靠 suspend 擋重建」。詳見 `design.md` D11
- [ ] 2c.2 模板無法表達「不部署任何 claude-code instance」：`claude_instances: []` 會讓 helmrelease 渲染為空並被 makejinja 略過，但 `instances/kustomization.yaml` 硬寫 `resources: [./helmrelease.yaml]`，kustomize build 隨即失敗
- [ ] 2c.3 弱測試憑證 + 預設啟用的公開入口是危險組合：`ttyd_credential` 若為測試值，配上預設 `claude_instances: ["im"]` 與出站自動連通的 tunnel，會讓 hostname 進 CT log。（本次實測確認 `replicas: 0` 使其不至於真的可登入，但該防護不應是唯一一道）

- [x] 2c.6 `local-path` 叢集原本**沒有 default StorageClass**：`sc-nas` 隨 nfs-subdir 一起移除後，叢集沒有任何 storage class（`storage/local-path-provisioner` 是 extra，未啟用）。已修：`ks.yaml.j2` 在 `storage_backend == 'local-path'` 時把它加進 Kustomization 清單，不論 `extras:` 有沒有列——profile 的預設 class 必須真的存在，而不只是「不是錯的那個」

- [x] 2c.7 `local-path` + 多節點改為明示選擇（方案 B）：CUE 要求 `single_node` 必須宣告；多節點時另需 `accept_node_pinning: true`，缺值或 `false` 皆拒絕。實作上繞過三次 CUE 自我滿足的陷阱，見 `design.md` D13
- [ ] 2c.8 （方案 A，後續）在 jg-base 實作複製式 block storage（Longhorn / Rook-Ceph）並新增第三個 `storage_backend` 值。jg-jiahd 是 3 節點，這不是假想需求

- [x] 2c.9 claude-code 的 `coding` volume 硬寫 `type: nfs`：無 NAS 時 `server`/`path` 渲染成空字串，chart schema 拒絕，**整個 release 裝不起來**。已改為由 `nas_coding_path` 條件渲染
- [x] 2c.10 claude-code 兩個 PVC 硬寫 `storageClass: sc-nas` → 改用 `default_storage_class`；同時 `replicas: 0` 配上 `WaitForFirstConsumer` 會讓 Helm 等一個依定義不會發生的綁定，已加 `install`/`upgrade` 的 `disableWait: true`。NFS 的 `Immediate` 綁定讓這個相撞在有 NAS 的叢集上不會出現
- [x] 2c.11 jg-base `storage` namespace 缺 PodSecurity 標籤，Talos 預設 `baseline` 擋掉 local-path provisioner 的 hostPath helper pod：provisioner 本身 Running、Kustomization Ready，但 PVC 永遠 Pending，錯誤只留在 PVC event。已於 jg-base `05b1501` 標為 `privileged`
- [x] 2c.12 上述五項合起來是同一個假設的五個位置（claude-code 長在有 NAS 的叢集上），且**全部只在 `local-path` 出現**——即 appliance 的標準組態。已在 jgt-omni 端到端驗證 `im.janncot.cc`：pod `1/1 Running`、兩個 PVC Bound 於 local-path、憑證 Ready、HTTP 401（ttyd basic auth，預期值）。詳見 `design.md` D14

- [x] 2c.13 `storage/local-path-provisioner` 由 extra 改為 base app 且永不 suspend（jg-base `3d87da3`）：它不是 NFS 的替代方案而是 node-local 層，有 NAS 的叢集同樣需要（否則 6.4 在 jg-jiahd 無處可放 DB）。`ks.yaml.j2` 的 auto-add 移除，改列入 `_now_base`。已在 jgt-omni 實測遷移完成：`local-path-provisioner` 現由 `cluster-apps-base` 擁有、路徑指向 `apps/base/`、StorageClass 回歸、PVC 全程 Bound。詳見 `design.md` D15
- [x] 2c.14 `accept_node_pinning` 的 predicate 已改為 `_uses_node_local`：`storage_backend == 'local-path'` **或** 啟用了 `#BlockTierExtras`（`claudecode/postgres`、`default/mariadb`、`default/postgres`、`freepbx/freepbx`）任一。有 NAS 的多節點叢集跑 DB 一樣被釘死，只是路徑不同，舊 predicate 會直接放行。`extras` 因此由 optional 改為 `*[] | [...string]`，讓判斷式能無條件讀取。七種組合皆已用 `cue vet` 驗證（含「nfs + 多節點 + 無 DB extra → 通過」與「nfs + 多節點 + postgres → 拒絕」）
- [x] 2c.15 jg-base README 的 extras→base 遷移 runbook 是錯的，且從未被執行過（jcom 事後補寫）。實跑後 release 照樣被 uninstall：`spec.prune` 不管刪除串聯——CRD 定義 `deletionPolicy` 才是，`MirrorPrune` 才會讀 `prune`，而本模板每個 Kustomization 都明寫 `deletionPolicy: WaitForTermination`；且線上 patch 會被母 Kustomization 的下次 apply 覆蓋，suspend 母體也不可靠（`Kustomization/flux-system` 由 flux-operator 管）。已改為「走 git 分兩次 push」（jg-base `db2568a`），詳見 `design.md` D16

## 3. 既有叢集遷移（不改變行為）

- [x] 3.1 **已對 jg-jiahd 實際套用**（2026-08-11）。先在完整副本驗過再上線，結果與副本逐字相同：`ks.yaml` **byte-identical**（唯一差異是把過期註解 `jgu5` 改成 `jg-jiahd`——repo 2026-05-30 已改名），`cluster-secrets` **+7 鍵、0 變更、0 移除**：4 個空的 `BACKUP_R2_*`、`DEFAULT_STORAGE_CLASS` 與 `DB_STORAGE_CLASS` 皆為 `sc-nas`、`LOCAL_PATH_IS_DEFAULT=false`。上線後全部 Kustomization Ready、`sc-nas (default)` 未變、`postgres-data` PVC 仍是 2026-06-19 那一個、`cc` pod 未重啟
  - 只同步了 ② 需要的 4 個檔案（schema / plugin / cluster-secrets / ks.yaml.j2），並把 jg-jiahd 的 QUIC workaround 重貼回去。**其餘仍分歧**：無 `templates/config/talos/`、無 `nodes.yaml` 與 `nodes.schema.cue`、無 `.taskfiles/talos/`、無 `check-template-integrity.py`、`bootstrap` 與 claude-code 模板仍是舊世代（`cc` 的 `replicas: 1` 與 image tag 是刻意的本地值）。完整世代同步屬 ① / ⑤，不在 3.1 範圍
- [ ] 3.2 jcom 遷移——仍阻塞於 `reconcile-jcom-lineage`：其 `templates/` 是更舊的世代（`SECRET_DOMAIN`、無儲存分層鍵），`task configure` 渲不出 `DB_STORAGE_CLASS`
  - [x] 3.2a **但 jcom 被 2c.13 弄壞了，已修**：`storage/local-path-provisioner` 移入 base 後，jcom 的 `extras:` 仍列著它，`extras-local-path-provisioner` 指向已不存在的路徑而 NotReady（約 72 分鐘）。資源全程安全——該 Kustomization 建不起來就不會 prune。修法是從 `extras:` 移除後 `task configure`，渲染差異恰好只有那一個 Kustomization 區塊，secret 值 0 變更
- [x] 3.3 未遷移時 `cue vet` 擋下且 `kubernetes/` 完全未被寫入（實測 0 個變更）

## 4. LAN 位址配置（jg-base）

- [ ] 4.1 實作 LAN 位址探測元件：hostNetwork + CAP_NET_RAW，ARP 掃描節點所在子網
- [ ] 4.2 讓探測結果以 `CiliumLoadBalancerIPPool` 為唯一對外輸出，重啟後重現同一位址
- [ ] 4.3 為 `envoy-internal` / `mqtt` /（fallback）`k8s-gateway` 加上 `sharing-key` 與 `sharing-cross-namespace`（**兩邊都要掛**，缺一邊會 unassigned）
- [x] 4.6 已實作（jg-base `9b1530e`）。`pool` 保留 `cidr: ${NODE_CIDR}` 但加上 `disabled: ${LB_POOL_WIDE_DISABLED:=false}`，新增 `pool-narrow` 由 `${LB_POOL_BLOCKS:=[]}` 提供逐一位址的 range。**靠停用寬 pool 來收窄，不是加一個更窄的**——1.5 已證明最舊者勝，加窄的沒用。
  - 兩個變數的預設值都等於今日行為：cluster-secrets 還沒有這兩個鍵的叢集維持寬 pool + 空的 `pool-narrow`（空 pool 就是沒東西可發，無害）。**這一點是必要的**：CRD 並未要求 `blocks`，空的 blocks 會被接受並靜默清空整個 pool，所以「沒有預設值」不是安全的失敗，是無聲的斷線
  - envsubst 無法表達「退回 `NODE_CIDR`」：巢狀預設值裡的 `}` 會提前終止運算式，連帶把 YAML 弄壞（已用 `flux envsubst` 實測，設值與不設值兩種情況都壞）
  - 一併移除 jg-base 內兩個寫死的位址：`10.9.1.2`（mariadb）與 `10.9.8.8`（omni），與 6.1 的 NAS IP 同一類缺陷。兩者都以原字面值作為 substitution 預設值，未遷移的叢集行為不變
  - 三個活叢集的推導結果已與實際配發位址逐一比對，完全吻合（jg-jiahd 4 個、jcom 6 個、jgt-omni 3 個）。`cluster_api_addr` 刻意不納入——它是 Talos VIP，不是 Service
  - **已上線 jgt-omni 與 jg-jiahd**。兩段都先驗證「未帶變數時是 no-op」（`pool-narrow` 存在但為空、寬 pool 仍啟用、服務不變），再推 per-user 變數翻轉。切換皆在 10 秒內完成，位址一個沒掉，全部 Kustomization Ready
  - **危害已實證關閉**：narrow 後在 jgt-omni 建一個未釘位址的 LoadBalancer Service，得到 `ip=<none>` 與 *There are no enabled CiliumLoadBalancerIPPools that match this service*——在此之前它會拿走 `10.9.1.1`（LAN 閘道）並 ARP 廣播
  - jcom 尚未套用（模板世代較舊，見 3.2），維持寬 pool——這正是預設值要保障的情況，其服務全程未受影響
  - 4.8 一併踩到一個坑：`CiliumL2AnnouncementPolicy` **只有 v2alpha1**，我把整份檔案改成 v2 導致整個 manifest dry-run 失敗、Kustomization NotReady。Flux 的 dry-run 擋在套用之前，pool 與服務都沒被動到；已修正（jg-base `2fa30b6`）
- [ ] 4.7 appliance 下把 `envoy-external` 改為 ClusterIP，並確認 cloudflared 仍經 `envoy-external.network.svc.cluster.local:443` 正常運作
- [x] 4.8 `networks.yaml` 的 apiVersion 已改為 `cilium.io/v2`（叢集實際服務且儲存的版本），隨 4.6 一併變更
- [ ] 4.9 讓 daily-check 監看所有 LoadBalancer Service 的 `cilium.io/IPAMRequestSatisfied` 條件
- [ ] 4.4 實作指派後的持續撞號監看，並在確認撞號時自動改選、記錄新舊位址
- [ ] 4.5 撰寫探測元件的替換說明：DHCP lease-holder 須產出相同的 pool，且不得要求 pool 以外的任何變更

## 5. 內網服務 DNS（jg-base）

- [ ] 5.1 新增第二份 external-dns 實例，`--gateway-name=envoy-internal`、關閉 proxy
- [ ] 5.2 設定與現有實例分離的 `txtPrefix` 與 `txtOwnerId`，並驗證兩者 full sync 後互不刪除對方記錄
- [ ] 5.3 把 `k8s-gateway` 改為條件啟用，appliance 預設不部署
- [ ] 5.4 依 1.4 的結論實作 rebinding protection 偵測與偵測結果的回報路徑
- [ ] 5.5 驗證啟用 `k8s-gateway` fallback 前後 hostname 與 LAN 位址不變（零客戶端遷移）
- [ ] 5.6 驗證外部路由（`envoy-external`）的發佈行為與今日完全相同

## 6. 儲存分層（jg-base）

- [x] 6.1 **原診斷是錯的**：`storageClassName: ""` 在這裡不是 bug。它與同一份 manifest 裡的 PV 以 `volumeName` 靜態綁定，這是既有 NFS export 的正確用法，會立刻 Bound，不會 Pending。掃描找到的真缺陷是另一個：`server: 10.9.2.13`（ferry133 自己的 NAS）被寫死在 ~20 個叢集共讀的 repo 裡。已改為 `${NAS_SERVER}`（jg-base `676f311`）；在唯一啟用這些 extras 的叢集上解析為同一位址，PV 未變動——PV 的 `nfs.server` 是 immutable，這點必須先確認才能推。spec 的該條需求已一併改寫
- [x] 6.2 掃描完成：13 處 `storageClassName: ""` 全為靜態 PV/PVC 配對；4 個檔案寫死 NAS IP（linebot ×2、synophoto、default/postgres backup），已修。export path（`/volume3/knowledge` 等）仍為字面值——只有原生叢集啟用這些 extras，列為已知限制而非默默帶著
- [x] 6.3 無 NAS 的叢集原本**完全沒有 default StorageClass**：nfs-subdir 宣告 `defaultClass: true` 但在該處被 suspend，local-path 則從未宣告。已改為 `defaultClass: ${LOCAL_PATH_IS_DEFAULT:=false}`，其值恰在 nfs-subdir 未運行時為 true，兩者永不相撞。已在 jgt-omni 實測：`local-path (default)`，且一個不指定 class 的 PVC 成功 Bound → 掛載 → 寫入
- [x] 6.4 DB 資料卷改用 `${DB_STORAGE_CLASS}`（`claudecode/postgres`、`default/mariadb`、`default/postgres`）。`default/postgres` 原本**完全沒寫 class**，於是在 NFS 叢集上資料目錄靜默落在 `sc-nas`。substitution 預設值取 `sc-nas` 而非正確的 block tier：PVC 的 `storageClassName` 是 immutable，預設值只會在尚未遷移到 profile schema 的叢集上生效，而那些全是 DB 已在 NFS 上的 NFS 叢集——預設值的意思是「維持現狀」，真正的搬遷仍須 dump/restore。freepbx 已在 block tier，不動
- [x] 6.5 claude-code 工作區改用 profile 預設 class（已於 2c.9/2c.10 完成）
- [x] 6.6 已驗證：設了 `nas_coding_path` 時 `coding` 掛載渲染結果與先前逐字相同（`type: nfs` + `${NAS_SERVER}`）；未設時整段不存在，兩個 PVC 落在 `local-path`
- [ ] 6.7 既有叢集的 DB 搬遷 —— **2026-08-11 決定延後**，改以 `db_storage_class: "sc-nas"` 明寫標記待辦。理由與現況：

  | | jg-jiahd | jcom |
  |---|---|---|
  | 節點 | 3 | **1** |
  | PVC | `db/postgres-data` 5Gi sc-nas | `claudecode/postgres-data` 5Gi sc-nas |
  | DB 大小 | 8.7 MB | 7.7 MB |
  | 日備份 | 正常，保留 14 份 | 正常 |
  | 釘死代價 | **真實**——3 選 1 | **無**——本來就單節點 |
  | 阻塞於 | 3.1（模板世代同步） | 3.2 → ⑤ |

  jg-jiahd 選擇保留 sc-nas，等 2c.8 的複製式儲存到位再一次到位——搬到 local-path 是拿「可跨節點重新排程」換「正確的 fsync/鎖語意」，而 2c.8 兩者都給。jcom 單節點本無代價，但其 `templates/` 是更舊的世代（`SECRET_DOMAIN`、無儲存分層鍵），`task configure` 渲不出 `DB_STORAGE_CLASS`，必須先過 ⑤。

- [x] 6.8 `_uses_node_local` 再修一次：`db_storage_class` 明寫為非 node-local 的 class 時，DB 就不在 node-local 上，pinning 閘門不該再問。predicate 改為 `storage_backend == "local-path"` **或**（`db_storage_class == "local-path"` **且** 有 block-tier extra）。這個錯誤是由 6.7 的決定當場暴露的——選了「不搬」才發現 schema 會要求承認一件不會發生的事。六種組合已驗證
- [x] 6.9 **還原演練**（延後搬遷的直接後果：jg-jiahd 的 DB 繼續待在 NFS 上，失效模式是靜默損毀，而唯一的救援就是那份日備份——它的 restore 半邊從未被執行過）。已在 jg-jiahd 以唯讀掛載備份卷的拋棄式 postgres 實測 `linebot-20260810.sql.gz`：10 張表列數與生產**逐表相同**，restore 0 error。前置條件一併查出：**必須先建 `linebot` role**，否則 dump 裡的 `OWNER TO` 全數失敗（表仍會建，但擁有者變成 postgres）。演練 pod 已刪除

## 7. Appliance 備份（jg-base）

- [ ] 7.1 實作備份 CronJob：`pg_dump` + agent 工作區 → age 加密 → Cloudflare R2
- [ ] 7.2 確認備份內容不含 Git 已追蹤的 manifests
- [ ] 7.3 驗證僅憑 R2 憑證無法解密任何內容
- [ ] 7.4 在 `monitoring/daily-check` 加入備份新鮮度回報，逾期時扣住 dead-man switch ping
- [ ] 7.5 確認非 appliance 且未設定備份的叢集，daily-check 仍印出「not configured」並 exit 0
- [ ] 7.6 建立 `age.key` escrow 流程，並將「escrow 完成」列為 provisioning 完成的條件

## 8. 驗收

- [x] 8.7 收窄 pool 的驗收**不能**問「narrow 之後有沒有壞」——漏列位址時那個問題也會答「沒有」。必須在套用前證明 pool 涵蓋當下每一個已配發位址（`kubectl get svc` 的實際集合 vs 渲染出的 `LB_POOL_BLOCKS`）。已配發的位址不會因來源 pool 消失而被收回，要到 Service 下次重建才失敗。詳見 `design.md` D26。已實作為 `scripts/check-lb-pool-covers-live.py`，套用前對 jgt-omni 與 jg-jiahd 各跑一次皆通過

- [ ] 8.1 在 scratch 叢集完成一次 appliance profile 全新部署，客戶端輸入為 0 項
- [ ] 8.2 從 LAN 用戶端驗證內網服務可用扁平 hostname 存取，且未變更路由器或裝置設定
- [ ] 8.3 完成還原演練：僅用備份封存 + escrow 的 `age.key`，在新叢集還原並比對資料一致
- [ ] 8.4 撰寫還原程序文件，內容須與演練實際步驟逐字一致
- [ ] 8.5 回寫所有 spike 結論到 `design.md` 與相關 spec，確認無「待驗證」項目遺留
- [ ] 8.6 每個 profile 的驗收都必須**在該 profile 上實跑到工作負載就緒**，不得只驗 `task configure` 的輸出。2c.9–2c.11 那四道渲染期缺陷全部無聲通過了 `task configure`（見 `design.md` D14）

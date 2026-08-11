## 1. Spikes（先做，結果會改變後面的設計）

- [x] 1.1 驗證 Cilium LB-IPAM `lbipam.cilium.io/sharing-key` 跨 namespace 支援 — 2026-08-09 於 jg-jiahd (v1.19.1) 實測，可行；結論見 `design.md` D3
- [x] 1.2 內網共用位址數量確定為 1，已回寫 `design.md` D3/D3a 與 `specs/lan-address-allocation/spec.md`
- [ ] 1.3 實測 Cloudflare DNS 接受 RFC1918 A 記錄的行為（DNS-only 可行、proxied 應失敗），記錄實際錯誤訊息
- [ ] 1.4 決定 DNS rebinding protection 的偵測方式（節點 hostNetwork 查詢路由器 resolver vs 客戶端回報），回寫 `design.md` Open Questions
- [ ] 1.0 appliance 是單節點，而 `jg-base/.../kube-system/kustomization.yaml:12` **無條件**部署 Spegel。**2026-08-10 已在測試機重現**：pod 永遠 `0/1`（`routing table is empty after bootstrapping`——單節點無 peer），且仍寫入 `_default/hosts.toml` 把所有 registry 導向本機死埠。惟 **image 拉取未受影響**（containerd 2.2.6 於 200ms 逾時後回退上游成功），故 jcom 記錄的「全叢集拉不動」應為舊 containerd 2.1.6 的行為。profile 仍須關掉 Spegel，但非緊急。詳見 `docs/template-lineage.md`
- [ ] 1.5 在 scratch 叢集驗證：服務同時匹配窄 pool 與寬 pool 時 Cilium 的選擇順序（不可在有真實裝置的 LAN 上測，寬 pool 自動配發會取 `10.9.9.1`）
- [ ] 1.6 在 scratch 叢集驗證：單一位址 pool 下，port 衝突的服務是否落到 Pending 並回報 `IPAMRequestSatisfied=False`
- [ ] 1.7 驗證 Envoy Gateway 的 `spec.infrastructure.annotations` 會把 `sharing-key` / `sharing-cross-namespace` 傳導到產生的 Service

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

- [x] 3.1 jg-jiahd 副本補 `deployment_profile: "full"` + `storage_backend: "nfs"`：`ks.yaml` 完全相同，`cluster-secrets` 僅**新增** 4 個空的 `BACKUP_R2_*`，既有值未變
- [ ] 3.2 jcom 遷移——阻塞於 `reconcile-jcom-lineage`：jcom 是另一支血脈，無法直接套用模板（見該 change）
- [x] 3.3 未遷移時 `cue vet` 擋下且 `kubernetes/` 完全未被寫入（實測 0 個變更）

## 4. LAN 位址配置（jg-base）

- [ ] 4.1 實作 LAN 位址探測元件：hostNetwork + CAP_NET_RAW，ARP 掃描節點所在子網
- [ ] 4.2 讓探測結果以 `CiliumLoadBalancerIPPool` 為唯一對外輸出，重啟後重現同一位址
- [ ] 4.3 為 `envoy-internal` / `mqtt` /（fallback）`k8s-gateway` 加上 `sharing-key` 與 `sharing-cross-namespace`（**兩邊都要掛**，缺一邊會 unassigned）
- [ ] 4.6 把 `networks.yaml` 的 pool 從 `cidr: ${NODE_CIDR}` 收窄為只含實際使用的位址（同時修掉既有的寬 pool 風險）；`full` profile 需逐叢集列出現用位址後才套用
- [ ] 4.7 appliance 下把 `envoy-external` 改為 ClusterIP，並確認 cloudflared 仍經 `envoy-external.network.svc.cluster.local:443` 正常運作
- [ ] 4.8 把 `jg-base` 的 `CiliumLoadBalancerIPPool` apiVersion 從 `v2alpha1` 更新為叢集實際服務的 `cilium.io/v2`
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
- [ ] 6.7 既有叢集的 DB 搬遷（jg-jiahd `default/postgres`、jcom `claudecode/postgres`）：需 dump → 刪 PVC → 以 block class 重建 → restore。`db_storage_class` 欄位讓「還沒搬」變成 cluster.yaml 裡看得見的一行，而不是靜默狀態

## 7. Appliance 備份（jg-base）

- [ ] 7.1 實作備份 CronJob：`pg_dump` + agent 工作區 → age 加密 → Cloudflare R2
- [ ] 7.2 確認備份內容不含 Git 已追蹤的 manifests
- [ ] 7.3 驗證僅憑 R2 憑證無法解密任何內容
- [ ] 7.4 在 `monitoring/daily-check` 加入備份新鮮度回報，逾期時扣住 dead-man switch ping
- [ ] 7.5 確認非 appliance 且未設定備份的叢集，daily-check 仍印出「not configured」並 exit 0
- [ ] 7.6 建立 `age.key` escrow 流程，並將「escrow 完成」列為 provisioning 完成的條件

## 8. 驗收

- [ ] 8.1 在 scratch 叢集完成一次 appliance profile 全新部署，客戶端輸入為 0 項
- [ ] 8.2 從 LAN 用戶端驗證內網服務可用扁平 hostname 存取，且未變更路由器或裝置設定
- [ ] 8.3 完成還原演練：僅用備份封存 + escrow 的 `age.key`，在新叢集還原並比對資料一致
- [ ] 8.4 撰寫還原程序文件，內容須與演練實際步驟逐字一致
- [ ] 8.5 回寫所有 spike 結論到 `design.md` 與相關 spec，確認無「待驗證」項目遺留
- [ ] 8.6 每個 profile 的驗收都必須**在該 profile 上實跑到工作負載就緒**，不得只驗 `task configure` 的輸出。2c.9–2c.11 那四道渲染期缺陷全部無聲通過了 `task configure`（見 `design.md` D14）

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
- [x] 2.8 `ks.yaml.j2` 依 `storage_backend` 過濾 extras：非 nfs 時跳過 `storage/nfs-subdir`（實測 extras 2→1）
- [x] 2.9 `cluster-secrets.sops.yaml.j2` 加入 `BACKUP_R2_*`；並為改成 optional 的位址與 NAS 欄位補上顯式 `default()`（原本無防護，makejinja 的 chainable-undefined 會靜默渲染成空字串）
- [x] 2.10 `cluster.sample.yaml` 重組：新增 §0 Profile 置頂，標註 `(appliance: n/a)` 的欄位，NAS 改為條件必填，新增備份區塊
- [x] 2.11 三個 profile 各跑一次完整 `task configure` 皆通過，輸出符合預期（appliance 位址空/備份有值/extras 被過濾；full 位址與 NAS 齊全；prosumer+talos 的 coredns 推導為 10.43.0.10）

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

- [ ] 6.1 修正 `apps/extras/default/postgres/app/backup.yaml:13,26` 的 `storageClassName: ""`
- [ ] 6.2 掃過 `jg-base` 所有 PVC，確認無其他 `storageClassName: ""`
- [ ] 6.3 依 profile 設定預設 storage class（appliance → `local-path`）
- [ ] 6.4 把 PostgreSQL 與 agent memory 的 PVC 改為 block-backed class
- [ ] 6.5 把 claude-code 工作區改為未設定 `nas_coding_path` 時使用 profile 預設 class
- [ ] 6.6 確認 `nas_coding_path` 已設定時的 NFS 掛載行為不變

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

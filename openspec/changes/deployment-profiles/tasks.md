## 1. Spikes（先做，結果會改變後面的設計）

- [x] 1.1 驗證 Cilium LB-IPAM `lbipam.cilium.io/sharing-key` 跨 namespace 支援 — 2026-08-09 於 jg-jiahd (v1.19.1) 實測，可行；結論見 `design.md` D3
- [x] 1.2 內網共用位址數量確定為 1，已回寫 `design.md` D3/D3a 與 `specs/lan-address-allocation/spec.md`
- [ ] 1.3 實測 Cloudflare DNS 接受 RFC1918 A 記錄的行為（DNS-only 可行、proxied 應失敗），記錄實際錯誤訊息
- [ ] 1.4 決定 DNS rebinding protection 的偵測方式（節點 hostNetwork 查詢路由器 resolver vs 客戶端回報），回寫 `design.md` Open Questions
- [ ] 1.0 **（高優先）** appliance 是單節點，而 `jg-base/.../kube-system/kustomization.yaml:12` **無條件**部署 Spegel。jcom（1 節點）實際踩過：Spegel 起不來，臨死前寫 `hosts.toml` 把所有 registry 導向死掉的 `:29999/:30021`，**全叢集未快取的 image 都拉不動**，只能手動 patch `suspend: true` 求生。每一台 appliance 都會重現此故障——profile 必須把 Spegel 關掉，不能靠 per-cluster patch
- [ ] 1.5 在 scratch 叢集驗證：服務同時匹配窄 pool 與寬 pool 時 Cilium 的選擇順序（不可在有真實裝置的 LAN 上測，寬 pool 自動配發會取 `10.9.9.1`）
- [ ] 1.6 在 scratch 叢集驗證：單一位址 pool 下，port 衝突的服務是否落到 Pending 並回報 `IPAMRequestSatisfied=False`
- [ ] 1.7 驗證 Envoy Gateway 的 `spec.infrastructure.annotations` 會把 `sharing-key` / `sharing-cross-namespace` 傳導到產生的 Service

## 2. CUE schema 與範本（jg-cluster-template）

- [ ] 2.1 在 `cluster.schema.cue` 加入 `deployment_profile`（三值、無預設）與 `storage_backend`（兩值）
- [ ] 2.2 把 `nas_server` / `nas_path` 改為 `storage_backend: nfs` 時才必填；`nas_coding_path` 維持 optional
- [ ] 2.3 把 `cluster_api_addr` / `cloudflare_gateway_addr` 在 appliance 下改為固定 `10.9.9.2` / `10.9.9.5`，並保留 `full` 的顯式覆寫
- [ ] 2.4 把 `cluster_gateway_addr` / `cluster_dns_gateway_addr` / `mqtt_lb_ip` 在 appliance 下改為不可填（由探測產出）
- [ ] 2.5 加入 `appliance` ⇒ 禁止手動 Talos node 設定的驗證規則
- [ ] 2.6 加入 `appliance` ⇒ 備份目的地設定必填的驗證規則
- [ ] 2.7 在 `templates/scripts/plugin.py` 補上 profile 相關預設值與衍生欄位
- [ ] 2.8 依 profile 條件化 `templates/config/kubernetes/flux/cluster/ks.yaml.j2` 的 Kustomization 渲染（appliance 不渲染 `storage/nfs-subdir`）
- [ ] 2.9 在 `cluster-secrets.sops.yaml.j2` 加入備份目的地相關變數
- [ ] 2.10 依 profile 重組 `cluster.sample.yaml`，appliance 區塊置頂並標明「客戶必填 0 項」
- [ ] 2.11 用三種 profile 各跑一次 `task configure --yes`，確認渲染結果符合預期

## 3. 既有叢集遷移（不改變行為）

- [ ] 3.1 為 jcom 的 `cluster.yaml` 補 `deployment_profile: full` + `storage_backend: nfs`，`task configure` 綠燈且 diff 為空
- [ ] 3.2 為 jg-jiahd 及其餘既有 user repo 做同樣處理
- [ ] 3.3 確認未遷移的 repo 會在 `cue vet` 失敗且 `kubernetes/` 未被寫入（fail fast 行為驗證）

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

## 1. Spikes（先做，結果會改變範圍）

- [x] 1.1 jcom `ks.yaml.j2` 的 54 行**全數為新增**，兩個區塊、皆附事故說明，無舊版殘留：Cilium native-routing override（jcom 託管 Omni，MTU 1370 過小導致 SideroLink WireGuard `sendmmsg: message too long`）與 Spegel suspend。兩者根因相同——單節點
- [x] 1.2 `cilium_bgp_enabled` / `cilium_loadbalancer_mode` 在 jcom 與 jg-jiahd **皆為 0 消費端**（死碼），僅 genie1 仍在用；`spegel_enabled` 在 jcom 有 2 個消費端，仍活著
- [ ] 1.3 評估 Spegel 在多節點叢集的實際效益——若不明顯，從 jg-base 移除比 gating 簡單。（已知：jg-jiahd 3 節點上 3/3 Ready，功能正常；單節點必壞）
- [ ] 1.4 決定 per-cluster 例外的機制形式（post-build substitution / overlay 目錄 / cluster.yaml 條件渲染），判準含「能否偵測未宣告漂移」
- [x] 1.5 **已由 ② 解決**：新增 `single_node` 欄位（Omni 路徑渲染期確實無從得知，`nodes` 恆為 `[]`），並衍生 `is_single_node`——appliance 恆真、手動 Talos 依節點數、其他 Omni 叢集未宣告時假設有 peer。詳見 `deployment-profiles` 2c.4

## 2. 分岔清冊

- [x] 2.1 清冊格式定為：項目 / 位置 / 分類（收進模板・從叢集移除・宣告為例外）/ 現況。產出於 `docs/template-lineage.md`
- [x] 2.2 jcom 全部 7 個漂移檔逐項分類完成，共 17 項；其中 9 項已由 ① 收回模板
- [x] 2.3 jg-jiahd 僅 1 項（QUIC → http2），屬真正的 per-cluster 例外，待遷移到新機制
- [x] 2.4 無「不知道為什麼在這裡」的項目——每一項都有可追溯的理由，兩個 `ks.yaml.j2` 區塊皆附事故註解
- [x] 2.5 已收回模板的 9 項列於清冊並標記完成，避免重複處理

## 2b. 盤點時新發現

- [ ] 2b.1 模板 `cluster.schema.cue` 宣告 `cilium_bgp_router_addr` / `cilium_bgp_router_asn` / `cilium_bgp_node_asn` / `cilium_loadbalancer_mode` 四個欄位，**模板、cluster-secrets、jg-base 皆零消費端**（僅 genie1 在用）——接上或移除
- [ ] 2b.2 採納 jcom 的 `validate-talos-config` 任務
- [x] 2b.3 已採納 jcom 的 `cloudflare-tunnel.json` 前置檢查（由 `revive-talos-path` 5c.3 實作；2026-08-11 實測第二次踩到才修）
- [ ] 2b.4 單節點的 Cilium 設定（native routing + MTU 1500）與 Spegel 同屬「單節點安全性」，一併納入 3.x
- [ ] 2b.5 genie1 是第三支更舊的血脈（5 個 namespace 的 app 模板），本 change 不涵蓋，但需記錄以免「模板的後裔」被誤認為只有兩個 repo

## 3. 單節點安全性（jcom 遷移的前提）

- [x] 3.1 **已由 ② 的 2.8 解決**，但作法與原本設想的不同：jg-base 那份 `kustomization.yaml` 沒有改，因為 Flux 無法從那一端拒絕建立 Kustomization。改由 per-user repo 依 `cluster.yaml` **生成 suspend patch**——與 jcom 手寫的那段同型，只是來源從漂移變成宣告
- [x] 3.2 **已由 ② 解決**：`is_single_node` 於 `plugin.py` 衍生，`ks.yaml.j2` 據此生成 spegel 的 suspend patch
- [ ] 3.3 `01-apps.yaml.j2` 的 bootstrap 側 gating 與 jg-base 側一致（目前兩處控制互相打架：bootstrap 有 `spegel_enabled`、jg-base 無條件）
- [ ] 3.4 驗證單節點叢集完全不部署 Spegel，且不需任何 per-cluster patch
- [ ] 3.5 驗證多節點叢集行為不變
- [ ] 3.6 處理爆炸半徑：元件失敗或被移除時，它寫入的 `hosts.toml` 等節點層設定必須還原，不得留下指向死埠的 registry 轉址
- [ ] 3.7 驗證元件缺席 / 失敗 / 停用三種情況下，image 仍可從原 registry 拉取
- [x] 3.8 已回報：`deployment-profiles` 1.0 已標記完成，並註明 gating 由 2.8 的 suspend patch 承擔、已在 jgt-omni（單節點）確認 `suspend=true` 且 pod 已清除

## 4. Per-cluster 例外機制

- [ ] 4.1 依 1.4 實作機制
- [ ] 4.2 例外宣告須記錄「解決什麼問題」與「什麼條件成立時可移除」
- [ ] 4.3 實作例外清單的檢視方式
- [ ] 4.4 驗證例外範圍受限：宣告範圍外的共用行為不受影響
- [ ] 4.5 驗證共用改進仍能到達有例外的叢集
- [ ] 4.6 實作未宣告漂移的偵測（手改共用模板檔須可被回報）
- [ ] 4.7 定義「同一例外出現於多個叢集 → 升格為設定選項」的流程

## 5. 遷移既有例外

- [x] 5.1 **不需要新機制——這個例外已經不存在了**。jg-base commit `140d14c`（2026-07-23）把 `TUNNEL_TRANSPORT_PROTOCOL: http2` 與 `TUNNEL_POST_QUANTUM: false` 收為全域預設，而 jg-jiahd 的 patch 設的正是同樣兩個值，已經多餘了三個星期
  - 移除前三方逐字比對：patch 內容、jg-base 預設、活叢集上實際生效的環境變數，完全一致
  - **這也讓 CLAUDE.md 的 troubleshooting 段落過期**：它寫著「為什麼不改 jg-base？其他 cluster QUIC 正常，default 保留 QUIC 較好」——jg-base 早就改了。待更新
- [x] 5.2 已移除並推送。渲染後該區段與 jgt-omni **逐字相同**，分歧消除；活叢集上 cloudflared 的兩個環境變數不變、pod 未重啟（140 分鐘未動），是真正的 no-op
  - 過程中我第一次切割破壞了 YAML 結構（留下孤立的 `spec: values:` 與連續兩個 `target:`），而 `task configure` 仍 rc=0——**YAML 可解析不代表語意正確**。還原後改以完整區塊比對移除
- [ ] 5.3 jcom 的 Spegel suspend 改由 3.x 的 gating 取代（不是遷移到例外機制——單節點是通則不是例外）
- [ ] 5.4 驗證 jcom 在 gating 生效後不再需要該 patch

## 6. jcom 同步

- [ ] 6.1 `cluster.yaml` 補 `provisioning_path: "talos"` 與 `cluster_svc_cidr: "10.43.0.0/16"`
- [ ] 6.2 `bootstrap-apps.sh` 改用模板版（固定 namespace 清單；jcom 的掃描版在現行目錄結構下會取到錯的 namespace）
- [ ] 6.3 處理 `makejinja.toml` 的 `trello-notifier.yaml`：jcom 無此檔，需補檔或讓該 data 檔成為可選
- [ ] 6.4 依清冊採納 / 移除其餘差異
- [ ] 6.5 **在副本上**完整同步並比對渲染輸出（加密檔解密後比對），逐項解釋差異
- [ ] 6.6 通過後才對真 repo 執行

## 7. 驗收

- [ ] 7.1 對已同步的 jcom 再套用一次後續模板變更，確認**不需手動合併**且其宣告的例外仍在
- [ ] 7.2 jg-jiahd 重跑 5.7 式比對，確認機制變更未影響它
- [ ] 7.3 人為在某叢集製造未宣告漂移，確認可被偵測並回報
- [ ] 7.4 單節點叢集端到端驗證：無 per-cluster patch 即可正常運作、image 拉取正常
- [ ] 7.5 回寫所有 spike 結論，確認無「待驗證」項目遺留

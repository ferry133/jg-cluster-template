## 1. Spikes（先做，結果會改變範圍）

- [ ] 1.1 逐項分類 jcom `ks.yaml.j2` 的 54 行差異：真 per-cluster 例外 vs 舊版殘留 vs 該收進模板
- [ ] 1.2 確認 `cilium_bgp_enabled` / `cilium_loadbalancer_mode` 是否仍有消費端（`spegel_enabled` 已確認仍在用）
- [ ] 1.3 評估 Spegel 在多節點叢集的實際效益——若不明顯，從 jg-base 移除比 gating 簡單
- [ ] 1.4 決定 per-cluster 例外的機制形式（post-build substitution / overlay 目錄 / cluster.yaml 條件渲染），判準含「能否偵測未宣告漂移」
- [ ] 1.5 Omni 路徑下渲染期如何得知節點數（`nodes` 恆為空）——與 `deployment-profiles` 的 profile 軸協調

## 2. 分岔清冊

- [ ] 2.1 建立清冊格式：檔案 / 差異 / 分類 / 理由 / 哪一邊較好
- [ ] 2.2 盤點 jcom 全部 7 個漂移檔，逐項分類（不允許「暫時保留」）
- [ ] 2.3 盤點 jg-jiahd 的 `ks.yaml.j2` 19 行
- [ ] 2.4 標記所有「不知道為什麼在這裡」的項目並查清
- [ ] 2.5 記錄已由 `revive-talos-path` 收回模板的項目（talos 工具鏈、`TEMPLATE_NODE_CONFIG_FILE`、`encrypt-secrets` 含 `TALOS_DIR`、kubeconform 接線），避免重複處理

## 3. 單節點安全性（jcom 遷移的前提）

- [ ] 3.1 讓 `jg-base/kubernetes/apps/base/kube-system/kustomization.yaml` 的 Spegel 可由設定停用
- [ ] 3.2 依 1.5 的結論，在模板渲染期表達「是否單節點」
- [ ] 3.3 `01-apps.yaml.j2` 的 bootstrap 側 gating 與 jg-base 側一致（目前兩處控制互相打架：bootstrap 有 `spegel_enabled`、jg-base 無條件）
- [ ] 3.4 驗證單節點叢集完全不部署 Spegel，且不需任何 per-cluster patch
- [ ] 3.5 驗證多節點叢集行為不變
- [ ] 3.6 處理爆炸半徑：元件失敗或被移除時，它寫入的 `hosts.toml` 等節點層設定必須還原，不得留下指向死埠的 registry 轉址
- [ ] 3.7 驗證元件缺席 / 失敗 / 停用三種情況下，image 仍可從原 registry 拉取
- [ ] 3.8 回報 `deployment-profiles` task 1.0 已具備所需機制

## 4. Per-cluster 例外機制

- [ ] 4.1 依 1.4 實作機制
- [ ] 4.2 例外宣告須記錄「解決什麼問題」與「什麼條件成立時可移除」
- [ ] 4.3 實作例外清單的檢視方式
- [ ] 4.4 驗證例外範圍受限：宣告範圍外的共用行為不受影響
- [ ] 4.5 驗證共用改進仍能到達有例外的叢集
- [ ] 4.6 實作未宣告漂移的偵測（手改共用模板檔須可被回報）
- [ ] 4.7 定義「同一例外出現於多個叢集 → 升格為設定選項」的流程

## 5. 遷移既有例外

- [ ] 5.1 jg-jiahd 的 QUIC workaround 先在新機制上重現並驗證行為不變
- [ ] 5.2 確認無誤後才移除其 `ks.yaml.j2` 的手寫 patch
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

## Context

這個 change 不是設計出來的，是 `revive-talos-path` 的驗收工作（task 5.7）撞出來的。原本只想確認「模板改動不會弄壞既有叢集」，結果發現 jcom 根本收不了模板更新。

2026-08-09 逐檔比對（相對 `revive-talos-path` 動工前的模板 HEAD）：

```
jcom                                                      jg-jiahd
──────────────────────────────────────────────────────    ────────
ks.yaml.j2                     54 行                      19 行
.taskfiles/template/Taskfile.yaml  31 行                   —
plugin.py                      22 行                       —
.taskfiles/bootstrap/Taskfile.yaml 14 行                   —
bootstrap-apps.sh              10 行                       —
Taskfile.yaml                   4 行                       —
makejinja.toml                  2 行                       —
```

jg-jiahd 只有一個檔漂移（QUIC workaround），所以模板改動能乾淨套用、渲染結果零 diff。jcom 則是另一支血脈：它保留了完整的手動 Talos 工具鏈，而模板在某個時點把那些檔案拿掉了。

分岔是雙向的。實際內容：

**jcom 有、模板沒有**
- `plugin.py` 的 `talos_patches`、三個 node 預設、`cluster_svc_cidr: '10.43.0.0/16'`、`cilium_bgp_enabled`、`spegel_enabled`、`cilium_loadbalancer_mode`
- `.taskfiles/template/Taskfile.yaml` 的 `TEMPLATE_NODE_CONFIG_FILE`、`validate-talos-config`、`validate-kubernetes-config`（kubeconform）、`encrypt-secrets` 含 `TALOS_DIR`
- `01-apps.yaml.j2` 用 `spegel_enabled` 做單節點 gating

**模板有、jcom 沒有**
- `trello-notifier.yaml` 作為 makejinja data 檔（jcom 無此檔 → 套用模板的 `makejinja.toml` 會讓渲染中止）
- `bootstrap-apps.sh` 改用固定 namespace 清單（jcom 仍是舊的掃 `kubernetes/apps/*/`，在現行結構下會取到錯的 namespace）

`revive-talos-path` 已經把前四項的前半段拉回模板了——其中 `encrypt-secrets` 含 `TALOS_DIR` 與 kubeconform 接線是**比對 jcom 才發現模板漏掉的**，等於 jcom 已經在幫模板抓 bug，只是沒有人在看。

## Goals / Non-Goals

**Goals:**
- jcom 回到「能把模板更新當例行操作」的狀態。
- 每一項差異都有歸屬與理由，不留「不知道為什麼在這裡」。
- 讓 per-cluster 例外有正式表達方式，止住製造分岔的機制。
- 單節點安全性由設定決定，不靠事後 patch。

**Non-Goals:**
- 不重新設計 Flux 的整體結構。
- 不處理 jg-jiahd 以外其他 user repo（同樣機制適用，但逐一遷移不在此範圍）。
- 不決定 Spegel 在多節點叢集上該不該留——那是獨立問題，只確保單節點不會被它害死。
- 不代替 `deployment-profiles` 定義 profile 軸；本 change 提供它需要的 gating 機制。

## Decisions

### D1. 根因是「產物被手改」，不是「有人偷懶」

`kubernetes/flux/cluster/ks.yaml` 是渲染產物，但每個叢集的例外都被手寫進它的 `.j2`。jcom 的 Spegel suspend、jg-jiahd 的 QUIC workaround，兩個都在同一個檔案。

問題在於：**手改過的模板檔，和「還沒同步的舊版本」在檔案層級長得一模一樣**。沒有任何訊號能區分「這是本叢集刻意的例外」與「這只是落後了」。所以每加一個 workaround，該叢集就更難吃更新，而下一個 workaround 又只能繼續手改——分岔是這個機制的必然產物。

因此本 change 的重點不是「把 jcom 合回來」，而是**拆掉製造分岔的機制**。只做合併不改機制，一年後會回到同一個地方。

### D2. 分類只有三種，且不允許「先放著」

每一項差異必須是「收進模板」「從叢集移除」「宣告為 per-cluster 例外」其中之一。刻意不提供第四種「暫時保留」——那正是現況，而現況的成因就是沒有人被迫做決定。

「不知道為什麼在這裡」的項目本身就是發現，必須查清楚再分類。

### D3. 收回模板的判準是「其他叢集也會受益」，不是「誰比較新」

`encrypt-secrets` 含 `TALOS_DIR`：任何走手動路徑的叢集都需要 → 收回。
`bootstrap-apps.sh` 的 namespace 掃描：jcom 的是舊版且在現行目錄結構下會取到錯的值，模板的固定清單是刻意修正 → jcom 改用模板版。

規格明訂採納時要記錄「哪一邊比較好」，避免同一個判斷被反覆重打。

### D4. Spegel 是單節點安全性的第一個案例，不是特例

jcom 的 patch 註解記錄了完整事故：Spegel 在單節點起不來，臨死前寫 `hosts.toml` 把**所有** registry 導向死掉的 `:29999/:30021`，全叢集未快取的 image 都拉不動。

`jg-base/kubernetes/apps/base/kube-system/kustomization.yaml:12` 至今仍**無條件**部署它。jg-jiahd 有 3 節點所以沒事，jcom 有 1 節點所以被害。而 `deployment-profiles` 的 `appliance` **就是單節點**——每一台都會重現。

所以這不能繼續用 per-cluster patch 解。規格因此要求兩件事：一是這類元件由設定 gating；二是**失敗必須被隔離**——一個元件起不來就讓全叢集拉不到 image，這個爆炸半徑本身才是主要問題，gating 只是止血。

*Alternative considered*：直接從 jg-base 移除 Spegel。列為 spike——若多節點上的實際效益不明顯，移除比 gating 簡單得多。

### D5. 完成的定義是「同步過一次」，不是「看起來對齊了」

規格把驗收設在實際跑一次模板同步並比對渲染結果（加密檔需解密後比對）。理由與 `revive-talos-path` 5.7 相同：那次也是先以為會乾淨，實際跑才發現一個 `cp` 打錯把根 Taskfile 蓋掉、以及檢查腳本自己誤判。宣稱不算數。

### D6. 遷移順序：先建機制，再遷例外，最後同步

若先同步再處理例外，jcom 的 Spegel suspend 會在同步過程中消失，而單節點 gating 還沒進去——那台叢集會在中間狀態下失去 image 拉取能力。所以順序不能顛倒。

## Risks / Trade-offs

- **jcom 是產線叢集** → 全程先在副本驗證；`revive-talos-path` 5.7 已經證明副本驗證可行且能抓到真問題。
- **拆掉手改機制會動到 jg-jiahd 的 QUIC workaround** → 該 workaround 必須先在新機制上重現並驗證，才能拆掉舊的；不可同時進行。
- **單節點 gating 需要渲染期知道節點數** → 手動路徑可從 `nodes` 得知，Omni 路徑不行（`nodes: []`）。這是實作上的真實困難，可能要靠 profile 或明確欄位表達，與 `deployment-profiles` 相依。
- **「收進模板」會讓模板變複雜** → 判準限定在「其他叢集也會受益」，只服務單一叢集的留在 per-cluster 例外。
- **分岔可能不只 jcom** → 其他 user repo 未盤點。本 change 建立的機制與清冊格式應可重用，但逐一遷移不在範圍內。

## Migration Plan

1. **盤點**：把 jcom 的 54 行 `ks.yaml.j2` 差異逐項分類（spike：多少是真例外、多少是舊版殘留）。
2. **建機制**：per-cluster 例外的表達方式先做出來並在副本驗證。
3. **單節點 gating**：先讓 Spegel 可由設定停用（jg-base + 模板），這是 jcom 遷移的前提。
4. **遷移例外**：jcom 的 Spegel suspend、jg-jiahd 的 QUIC workaround 改用新機制，各自驗證行為不變。
5. **同步 jcom**：在副本上套用模板，比對渲染輸出，逐項解釋差異，通過後才對真 repo 執行。
6. **回歸**：jg-jiahd 重跑 5.7 式的比對，確認機制變更沒有影響它。
7. **Rollback**：每一步都在副本先行；真 repo 的變更以 git 保留，可還原。

## Open Questions

- jcom `ks.yaml.j2` 那 54 行，實際上有多少是 per-cluster 例外、多少是舊版殘留？決定遷移工作量。
- `cilium_bgp_enabled` / `cilium_loadbalancer_mode` 還有消費端嗎，還是已是死碼？（`spegel_enabled` 確定仍在用。）
- Spegel 在多節點叢集上的實際效益如何？若不明顯，從 jg-base 移除比 gating 簡單。
- per-cluster 例外要用什麼形式：Flux post-build substitution、獨立 overlay 目錄、還是 `cluster.yaml` 驅動的條件渲染？三者對「能不能偵測未宣告漂移」的支援程度不同。
- Omni 路徑下渲染期如何得知節點數？`nodes` 恆為空，可能要靠 profile 或新欄位。
- 其他 user repo（jgu4 等）的分岔程度未知，是否要一併盤點？

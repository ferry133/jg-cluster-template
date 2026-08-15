## 1. 前置與裁定

- [ ] 1.1 輪替 jgt-appliance 的 R2 憑證（即 `deployment-profiles` 8.3b）。本 change 會讓更多
      資料流經這條管線，而那組憑證曾以明文存在於 ConfigMap（`deployment-profiles` D46）。
      驗證：舊憑證取回失敗、新憑證成功，且新值只存在於 SOPS 加密後的檔案
- [ ] 1.2 修正 `deployment-profiles` 的 `appliance-backup` spec 與 D9：備份範圍改為「資料庫層
      + 完整 agent 狀態」。這是該 change 8.5 的一部分，改完不要留下兩份互相矛盾的規格
- [ ] 1.3 在 `deployment-profiles` D8 補一行指向本 change：D8 的「工作區可重建」仍成立，但
      推導不出「其餘不必搬」——session 歷史與 memory 既不可重建也不在 DB 裡

## 2. agent 狀態封存（jg-base）

- [ ] 2.1 在 `claudecode` namespace 新增封存 job：掛 `claude-config` 與 `claude-workspace`，
      tar → age 加密 → 寫入**與 `monitoring/backup` 相同的 R2 prefix、相同 recipient**
- [ ] 2.2 排除清單以內容為準（design D9）：`.git` clone、套件目錄、build 產物、快取排除；
      memory 與 session 歷史保留。清單放 configMap，不寫死在 image
- [ ] 2.3 session 歷史的保留上限（design D9 / Risks）：實作在 job 裡，不是只寫在文件。
      驗證：以超過上限的資料實測一次，確認封存體積受控且 memory 未被連帶裁掉
- [ ] 2.4 憑證一併納入（design D4）。驗證：還原後的 instance 不需重新登入即可運作
- [ ] 2.5 `monitoring/daily-check` 分別回報兩個成員的新鮮度，**不合併成一個「有備份」**
      （design D3 的代價）。一真一假時整體判 FAIL
- [ ] 2.6 在 jgt-appliance 實跑：確認兩個成員都產出、都可解密、排除清單真的排除了東西
      （比對封存內容清單，不是只看體積）

## 3. on-demand 觸發（design D8）

- [ ] 3.1 確認兩個封存 job 都可用 `kubectl create job --from=cronjob/<name>` 直接觸發，
      且行為與排程一致。若不行，修到可行，不新增第二條管線
- [ ] 3.2 在 jgt-appliance 實跑一次 on-demand：產出可與排程產物以時間戳區分，失敗時 exit 非 0。
      **空上傳回報成功正是 D46 的失效模式**，這一項要專門驗
- [ ] 3.3 daily-check 的新鮮度把 on-demand 產物一併算入

## 4. office rescue instance（design D5 / D7）

- [ ] 4.1 **先決定 rescue instance 住在哪座公司叢集**（design Open Questions 第一題）。
      未答則本組其餘任務無法開始
- [ ] 4.2 受限 RBAC：rescue instance 在公司叢集內只有自己 namespace 的權限。
      **不可沿用 jg-base `claudecode/rbac.yaml` 的 cluster-admin SA**
- [ ] 4.3 憑證注入與撤銷路徑：該客戶的 `kubeconfig-sa` 與 repo push token 如何進來、
      用完如何撤銷。撤銷要寫成步驟，不是「記得刪掉」
- [ ] 4.4 驗證 4.2 的邊界：實際跑一次跨 namespace 的請求並確認被 RBAC 拒絕，
      不是讀 RoleBinding 推論
- [ ] 4.5 驗證 design D7：在**沒有**到客戶叢集網路路徑的情況下，完成一次 `cluster.yaml`
      編輯 → `task configure` → push，並確認客戶叢集下次 reconcile 套用
- [ ] 4.6 接手與交回的記錄機制（design D6）：接手時間、期間做了什麼、何時交回，
      記在該客戶的 repo，不是只在 agent 記憶裡
- [ ] 4.7 接手時在來源端登出 / 失效化（design D4），與 4.6 的記錄同一個動作完成

## 5. 還原演練（同時完成 `deployment-profiles` 8.3 的剩餘部分）

- [ ] 5.1 用 **escrow 副本**（非 repo 內的工作副本）的 `age.key` 取回並解密 jgt-appliance 的
      封存。用副本是重點——`docs/operations/age-key-escrow.md:39` 要求對副本做 restore-test，
      而 jgt-appliance 的 `age_key_escrowed: true` 至今未被任何人查證過
- [ ] 5.2 在公司叢集起 rescue instance，還原 5.1 的封存：資料庫逐表比對列數與內容
      （比照 `deployment-profiles` 6.9：先種入已知資料再比對），agent memory 逐項比對
- [ ] 5.3 驗「同一個 agent」而非「有存取權的新 agent」：問它封存前在來源叢集做過的事，
      要答得出來
- [ ] 5.4 確認全程未接觸 jgt-appliance：只用封存 + escrow 金鑰。這是「客戶機器全損」情境的
      唯一有效證明
- [ ] 5.5 回頭把 `deployment-profiles` 8.3 標為完成並註明由本 change 5.1–5.4 承擔

## 6. 文件

- [ ] 6.1 撰寫還原/接手程序文件（承接 `deployment-profiles` 8.4），兩種觸發各一節：
      遷移交接（叢集還活著，走 on-demand 封存）與災難重建（叢集沒了，走最近一次排程封存）。
      內容須與 §5 演練的實際步驟逐字一致
- [ ] 6.2 `docs/deploy/combinations.md` §7.5.3 回填連結：agent 不能自己做的三件事，
      改由 rescue instance 接手的路徑指向 6.1
- [ ] 6.3 §8 缺口表更新：`profile 遷移實跑` 與還原演練兩列依實際狀態改寫，
      不留下已完成卻仍列為缺口的項目

## 7. 驗收

- [ ] 7.1 端到端一次：在 jgt-appliance 上完成一次真實的 §7.5.1 profile 遷移，其中
      「刪 probe 舊 pool」與驗證半邊由 office rescue instance 接手。這是本 change 與
      `docs/deploy/combinations.md` §7.5 共同的驗收
- [ ] 7.2 design 的 open questions 逐項落定：rescue instance 落腳叢集（4.1 已答）、
      一客戶一 instance vs 切換、transcript 保留上限的值、git 歷史是否納入知識來源。
      未決的寫成新任務，不留在 design 裡

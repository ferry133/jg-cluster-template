## Context

`im` 是每座叢集的 base app（`claudecode/claude-code`），一個帶 cluster-admin 的 web
terminal。它不是客戶的工具，是**我們派駐在客戶站點、代客操作那座叢集的 agent**。

出貨策略把它當成擴充的執行者：minimal appliance 先起來，之後把叢集長成目標形態
（`docs/deploy/combinations.md` §7.5）。但單節點上有三件事 agent 不能對自己做——節點重開、
刪自己的 `claude-workspace` PVC、刪 LB pool（§7.5.3）。這三件正好落在擴充路徑上，所以後半段
必須由站點外的 instance 接手，而它得帶著這座叢集的完整歷史。

現況三個事實：

1. `monitoring/backup` 只做 `pg_dump`（`deployment-profiles` tasks 7.1）。上傳路徑
   2026-08-15 才首次成立（同 change D46）；還原半邊（8.3）未完成。
2. agent 的狀態在兩顆 PVC：`claude-config`（`~/.claude` + keyring）與 `claude-workspace`。
   **兩顆都不在任何備份裡。**
3. `appliance-backup` spec 要求備份含 agent workspace，與實作相反；回寫任務
   （`deployment-profiles` 8.5）未做。

## Goals / Non-Goals

**Goals:**

- 讓一個 `im` 能完整地在另一座叢集重新站起來，帶著它原本的記憶。
- 同一條管線支撐兩種觸發：遷移交接（叢集還活著）與全損重建（叢集沒了）。
- office 端接手時，不把公司叢集的權限一併交出去。
- 裁定 spec 與實作的矛盾，讓「封存涵蓋什麼」只有一個答案。

**Non-Goals:**

- 不做雙向同步或記憶合併（D6）。
- 不新增外部相依。R2、age、既有 CronJob 之外不引進任何東西。
- 不改 CUE schema，不改 `claudecode/postgres` 的 base/extra 定位（D2）。

## Decisions

### D1. 封存涵蓋整個 agent 狀態，不只資料庫層

`deployment-profiles` D8 的前半（工作區檔案可重建）在寫入契約成立時仍然對，但它推導不出
「其餘也不必搬」——session 歷史與 memory 在 `claude-config`，那是變更歷史的實際所在，
既不可重建也不在 DB 裡。

真正的判準不是「可不可重建」，是**搬過去之後那個 agent 是不是同一個**。半個 agent 比沒有
agent 危險：它看起來還記得，實際上少了三個月，而讀它的人不會知道少在哪裡。

原本反對的理由是跨 namespace——備份 job 在 `monitoring`、PVC 在 `claudecode`，掛不上。
那是實作便利性，不是原則，解法見 D3。

### D2. 不把知識塞進資料庫，也因此不必動 `claudecode/postgres` 的定位

「全部改成 DB 型態以便移轉」在傳輸上是對的直覺，但 Claude Code 的 session 與 memory
**本來就是檔案**，我們無法改變它寫在哪。要全進 DB 只能再加一個把檔案塞進資料表的同步 job
——那是拿資料庫當檔案傳輸層，多一層阻抗，體積一樣，而還原時還要再倒回檔案。

檔案維持檔案，用封存搬。連帶結論：早期版本要把 `claudecode/postgres` 升為 appliance 必備，
唯一理由是「知識只有進 DB 才會被備份」；D1 之後該理由消失，memory DB 回到單純的 recall
品質問題，維持 opt-in。省下的不只是一個欄位——還有 CUE schema 兩處改動、base app 上移的
prune 時序風險（`deployment-profiles` D21），以及下面那個推導缺陷。

> 順帶記下一個**尚未發生的**缺陷，留給下一次把 app 移進 base 的人：
> `cluster.schema.cue:120-122` 用 `extras` 是否含 `claudecode/postgres` 來推導
> `_uses_node_local`。哪天它真的上移為 base app，這個命中會靜默消失，於是一座確實把資料庫
> 放在節點本機碟的多節點叢集會算出 false，`accept_node_pinning` 的承認被跳過而沒有人拒絕過。
> 本 change 不觸發它，但它會等在那裡。

### D3. 跨 namespace 用第二個 job，不是把知識搬去遷就 job 的位置

`claudecode` namespace 起一個封存 job，掛得到那兩顆 PVC，產物寫進**同一個 R2 prefix、
用同一把公鑰加密**。`monitoring/backup` 不動。

**替代方案**：把 `monitoring/backup` 搬進 `claudecode`。否決——備份 job 屬於 monitoring，
搬過去是讓位置遷就一個掛載問題。兩個 job 一個 prefix，還原端看到的仍是一組封存。

代價：新鮮度要分別回報，否則一個成功一個失敗會被平均成「有備份」。daily-check 要分開列。

### D4. 憑證跟著搬，撤銷靠「切換即在來源端登出」

`claude-config` 掛著 gnome-keyring（Claude 的 OAuth token 在裡面，
`helmrelease.yaml.j2:283-287`）。那是我們自己的帳號憑證，不是客戶的，跨站點移動不涉及客戶
邊界；而封存本來就已經帶著客戶的資料庫上 R2，加進來不改變它的性質。

一個 token 存在兩個地方就沒辦法在一處撤銷——這個問題不用排除憑證來解，用 D6 的規則解：
**接手 = 來源端登出**，「兩處都有效」的窗口只存在於切換那一刻。兩件事本來就該同時發生。

### D5. rescue instance 是新種的受限實例，不是把 `im` 原樣搬過來

`im` 綁 `claudecode` 的 cluster-admin SA（jg-base `rbac.yaml`）。原樣複製進公司叢集，等於
把公司叢集的完整權限給了一個為客戶站點而設的 instance。

rescue instance 因此：在公司叢集內只有自己 namespace 的權限；對外持有的是**該客戶的**
`kubeconfig-sa` 與 repo push token；狀態由封存還原。它是同一個 agent 換了地方跑，但**不繼承
它在原叢集的權限形狀**——那個形狀屬於原叢集。

### D6. split-brain：接手即作廢，單向

rescue instance 接手後，客戶端 `im` 的狀態立即過期。規則：**接手即作廢**（含 D4 的登出），
客戶端恢復後從封存重新種回，不做合併。

**替代方案**：雙向合併或 last-write-wins。否決——agent 記憶沒有可靠的衝突解法，而「兩邊各說
各話」的記憶比沒有記憶更危險，因為兩邊都讀起來像權威。

### D7. 遠端執行面是 `git push`，不是 `kubectl`

擴充的實際動作是改 `cluster.yaml` → `task configure` → push；客戶叢集的 Flux 自己收斂。
rescue instance **不需要能連到客戶叢集**就能推進工作——客戶叢集只要出得了網到 GitHub。

這是這條路對 Omni / SideroLink 中斷免疫的原因，也是 `im`「不依賴 Omni 的入口」定位的對偶。
需要叢集連線的只有驗證半邊（§7.5.1 第 6 步），可以等連線恢復再補——**但補之前不算完成**，
§1 的原則不因為遠端而放寬。

### D8. on-demand 封存重用既有 CronJob

`kubectl create job --from=cronjob/<name>` 是既有動作（§6.5 對 daily-check 已這樣用）。
不新增第二條備份路徑：兩條路徑會分岔，而分岔的那一份會在最需要的時候被發現是舊的。

代價是 on-demand 與定時封存共用保留策略與命名，取回時靠時間戳分辨。可接受。

### D9. 排除清單以內容為準，不以 PVC 為準

不是「工作區備 / 不備」，而是排除可重建的內容：`.git` clone、套件目錄、build 產物、快取。
`~/.claude` 底下同理——transcript 全量會長很大，需要保留上限。

以 PVC 為單位切會同時犯兩種錯：連 20Gi 的 clone 一起搬，或連 memory 一起丟。

## Risks / Trade-offs

- **封存體積從 KB 級跳到 MB～GB 級** → D9 的排除清單與 transcript 保留上限是必要的，不是
  優化。上限要寫進實作而非文件，否則第一次遇到大叢集才會發現。
- **兩個 job 的新鮮度可能一真一假** → daily-check 分開列，不合併成一個「有備份」。
- **R2 憑證未輪替**（`deployment-profiles` 8.3b）→ 列為前置，不並行。更多資料流經一條憑證
  曾外洩的管線，是把已知問題放大。
- **憑證進封存**（D4）→ 封存本來就以叢集公鑰加密，持 R2 憑證者拿到的只是密文
  （`deployment-profiles` 7.3 已實測）。殘餘風險是 `age.key` 與封存同時失守，那個情境下
  客戶資料本來也全在裡面。
- **rescue instance 的權限形狀是新的**，jg-base 目前只有 cluster-admin 那一種 → 這是本
  change 唯一需要新 RBAC 的部分，也是最容易做成「先給 cluster-admin 之後再收」的地方。

## Migration Plan

1. 前置：`deployment-profiles` 8.3b 輪替 jgt-appliance 的 R2 憑證。
2. 修正 spec（D1）：`appliance-backup` 的範圍改寫，`deployment-profiles` 8.5 的一部分。
3. jg-base：`claudecode` 的封存 job（D3）+ 排除/保留清單（D9）。
4. on-demand 觸發（D8）→ 在 jgt-appliance 實跑。
5. rescue instance（D5）→ 在公司叢集起一次。
6. 還原演練：用 escrow 副本還原 jgt-appliance 的封存並逐項比對。**這一次同時就是**
   `deployment-profiles` 8.3 的剩餘部分，不分開做。
7. 端到端：一次真實的 §7.5.1 profile 遷移，交接點落在 rescue instance。

回退：全部是加法——多一個 job、多一個公司端元件。客戶叢集除了多一份封存之外不感知，
隨時可停。沒有不可逆的步驟。

## Open Questions

- **rescue instance 住在哪座公司叢集？** `jg-jiahd` 還是 `jcom`？它會持有客戶憑證，
  這不是隨便挑的。此題未答則 task 5.x 無法開始。
- 多客戶同時 rescue：一客戶一 instance（權限邊界乾淨、較貴）還是一 instance 切換客戶？
  傾向前者，無實測。
- transcript 保留上限的具體值，以及超過之後丟舊的還是丟細節。
- 客戶 repo 的 git 歷史要不要納入 rescue instance 的知識來源？repo 在 GitHub，clone 得到，
  但「哪些 commit 屬於這次擴充」目前沒有結構化記錄。

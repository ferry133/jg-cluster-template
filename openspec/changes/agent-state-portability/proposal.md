## Why

`im` 是代客操作的 agent——它住在客戶站點，代替我們操作那座叢集。維運上它必須能整個搬走：
單節點 appliance 上，agent 不能執行會讓自己下線的步驟（重開機、刪自己的 PVC、刪 LB pool，
見 `docs/deploy/combinations.md` §7.5.3），所以擴充的後半段必須由站點外的 instance 接手。
同一個機制也是災難復原——客戶機器全損時，只憑封存 + escrow 的 `age.key` 重建。

**半個 agent 比沒有 agent 危險**：它看起來還記得，實際上少了三個月。所以搬移必須是完整的。

今天做不到。封存只含 `pg_dump`（`deployment-profiles` tasks 7.1）；agent 的 session 歷史與
memory 在 `claude-config` PVC、工作區在 `claude-workspace` PVC，兩顆都不在任何備份裡。而
`appliance-backup` spec 要求備份含 "the database tier and the agent workspace"，與實作相反，
回寫 spec 的任務（`deployment-profiles` 8.5）未做——兩邊都還宣稱自己是對的。

還原半邊至今也沒跑完（`deployment-profiles` 8.3 為 `[~]`、8.4 未寫）。

## What Changes

- **封存範圍改為「整個 agent 狀態」**：`pg_dump` + agent 狀態 tar（`~/.claude` 與工作區中
  不可重建的部分）。**BREAKING**（對 spec 而非對叢集）：`appliance-backup` 的範圍要求改寫，
  原本「含 workspace」與實作「都不含」兩種說法都被取代。
- **跨 namespace 用第二個 job 解決**，不是把知識搬去遷就備份 job 的位置：`claudecode`
  namespace 起一個封存 job，產物寫進同一個 R2 prefix、用同一把公鑰加密。
- **憑證跟著搬**，並以「切換即在來源端登出」收斂撤銷問題——與 split-brain 規則同一條。
- **新增 on-demand 封存觸發**：既有 `monitoring/backup` 加一條「現在備一份」的路徑，
  遷移交接不必等隔天 02:00。
- **新增 office rescue instance**：公司叢集起一個受限的 claude-code instance，還原指定客戶的
  封存後接手。它**對公司叢集本身無 cluster-admin**——現有 `im` 綁的正是 cluster-admin SA，
  原樣複製等於把公司叢集交出去。
- **明訂遠端執行模型**：執行面是 `git push`（Flux 自行收斂），不是 `kubectl`。客戶叢集只要
  出得了網到 GitHub 就推得動，因此 Omni / SideroLink 中斷時這條路仍成立。
- **明訂 split-brain 規則**：接手後客戶端 `im` 作廢，恢復時從封存重新種回，不做雙向合併。
- **不動 `claudecode/postgres` 的 base/extra 定位**：它維持 opt-in。（早期版本曾打算升為
  appliance 必備，理由是「知識只有進 DB 才會被備份」——備份修好後該理由消失，見 design D2。）

## Capabilities

### New Capabilities

- `agent-state-recovery`: 從封存在另一座叢集重建一個具備原叢集記憶的 agent——含 on-demand
  封存、rescue instance 的權限形狀、遠端執行模型、憑證移轉與撤銷、split-brain 規則。

### Modified Capabilities

- `appliance-backup`: 備份範圍改為「資料庫層 + 完整 agent 狀態 + 不可從 git 重建的設定」；
  新增 on-demand 觸發與「封存必須足以重建一個完整的 agent」的驗收。該 spec 目前仍在
  `deployment-profiles` change 內（尚未 archive）。

## Impact

- `jg-base`：`claudecode` namespace 新增 agent 狀態封存 job；`monitoring/backup` 的 on-demand
  觸發路徑；rescue instance 的受限 RBAC（不可沿用 `claudecode/rbac.yaml` 的 cluster-admin SA）。
- `jg-cluster-template`：`docs/` 的還原/接手程序（承接 `deployment-profiles` 8.4）；
  `docs/deploy/combinations.md` §7.5.3 回填；回頭修 `deployment-profiles` 的
  `appliance-backup` spec 與 D9。**CUE schema 與 `cluster.sample.yaml` 不受影響。**
- `jgt-appliance`：唯一會被實際改到叢集狀態的 user repo，所有實跑在此進行。
- office cluster 的 user repo：rescue instance 的落腳處，**尚未指定**（見 design Open Questions）。
- `k8scc`：僅在保留/排除清單要內建進 image 時才動；預設放 jg-base 的 configMap。
- 前置：`deployment-profiles` 8.3b（jgt-appliance 的 R2 憑證輪替）——那組憑證曾以明文存在於
  ConfigMap，而本 change 會讓更多資料流經同一條管線。

## 1. Spikes（先做，結果會改變後面的設計）

- [x] 1.1 **有事件訂閱，不需要輪詢**（2026-08-16，讀 Omni 原始碼 `~/coding/omni`）
  - Omni 的資源存取就是 COSI state API，而它原生支援 watch：`safe.StateWatchKind` 訂閱某個
    resource type 的所有事件，`safe.StateWatch` 只看單一 ID。watch 活到 context 被取消為止，
    生命週期由消費端掌握（`client/pkg/client/example_test.go:130-141`）
  - 要訂閱的是 `MachineStatuses.omni.sidero.dev`（`omni.NewMachineStatus("")` 的 metadata 餵給
    `StateWatchKind`）。機器經 SideroLink 回連後就出現在這裡；同族的還有
    `Machines.omni.sidero.dev`
  - **順帶解掉一個本來要另外想辦法的問題**：`MachineStatusSpec` 帶著硬體清單——CPU、記憶體、
    以及每顆 block device 的 `linux_name` / `serial` / `wwid` / size（`client/api/omni/specs/omni.proto`）。
    那正是手動 Talos 路徑 `nodes.yaml` 需要的每節點磁碟選擇器。**偵測到新機器的同一個事件，
    就帶著建它所需的事實**，不必再開第二條查詢路徑
  - 兩個設計約束，會影響 §2 之後的形狀：
    1. **factory 不能靠 shell 出去呼叫 `omnictl`**——該 CLI 沒有暴露任何 watch 旗標
       （整個 `client/cmd/omnictl/` grep 不到 watch）。要用事件就得走 Go SDK 或直接打 gRPC
    2. watch 會送出 `state.Errored` 事件（範例在 `:151` 明確處理它），所以消費端**必須自己實作
       重連**。一個沒有重連的 watch 會安靜地停止收事件——與「沒有新機器」外觀完全相同，
       又是一個「看起來正常的失效」
  - **驗證邊界照實寫**：以上全部讀自原始碼與 SDK 範例，**沒有對活的 Omni 實跑過**。要實跑需
    先開 `CLAUDE.md` 記的 port-forward（`omni.janncot.com` 的 gRPC 端點走 localhost:18080），
    而「API 成本」這一半——若真要輪詢時的間隔與成本——因為結論是事件驅動而不再需要量
- [ ] 1.2 確認 Google Workspace Admin SDK 建立使用者所需的最小權限範圍，以及是否非用 domain-wide delegation 不可
- [ ] 1.3 確認 Cloudflare Tenant API 的取得條件；若不可得，評估「單一母帳號 + 每叢集 scoped token」能否支撐交接
- [x] 1.4 **不可轉移。交接走 Talos client cert，而那條路已經在生產中用著**（2026-08-16，讀 Omni 原始碼）
  - **Management API 完全沒有 export / import / transfer / adopt 這類 RPC**——把
    `client/api/omni/management/management.proto` 的 `rpc` 逐條看過（20 條），沒有任何一條能把
    一座 cluster 交出去。這是「介面上不存在」，不是「我沒找到用法」
  - 機器綁在哪一座 Omni，是**開機參數**決定的：`ConnectionParamsSpec` 帶 `api_endpoint`
    （該 Omni 的外部 gRPC 端點）、`wireguard_endpoint` 與 `join_token`，以 `args`（kernel
    arguments）形式送進機器。所以「改連客戶自己的 Omni」＝ 換 kernel args ＝ 換 schematic/ISO
    後重新註冊，而它在對面會是一台**全新的機器**，不是被交接過去的同一台
  - cluster 在 Omni 裡的身分（PKI、machine set 定義）沒有匯出路徑，所以「把 Omni cluster 的
    控制權轉移給客戶」在今天的 API 下不成立
  - **替代路徑現成**：Management API 有 `Talosconfig` 與 `Kubeconfig` 兩條 RPC，直接簽出 client
    憑證。而這不是紙上方案——`CLAUDE.md` 已記著 jcom 就是用 Talos client cert kubeconfig、
    不需要 `kubeconfig-sa`。交接要發的東西，我們自己每天在用
  - **驗證邊界**：讀的是目前 checkout 的 Omni 原始碼與 proto。「介面上沒有」是強證據但不等於
    Sidero 的產品承諾——若要「將來也不會有」這種等級的答案，得問 Sidero。以現況決策足夠：
    今天沒有這條路，交接就得發憑證

- [ ] 1.5 → 見下方改寫；等 `ferry133/jg-cluster-template#3` 定案
- [ ] 1.5 決定 factory 對客戶叢集憑證的存活期策略（長期持有 vs 每次向 Omni 重新取得），回寫 `design.md` Open Questions
  - **提案（2026-08-16）：客戶叢集憑證一律用時再取，不留存；factory 只長期持有一把——它自己的
    Omni SA key。** 理由來自 1.1 與 1.4 兩個結果，缺一個都推不出來：
    - 1.4 查出 Management API 有 `Talosconfig` / `Kubeconfig` / `CreateServiceAccount`，
      每座客戶叢集的憑證都能隨時現簽，所以「存起來」買不到任何東西
    - 1.1 查出 factory 是個握著 watch 的長駐 Go/gRPC 程序，用時取憑證對它是自然動作；
      如果它是個 shell 腳本，source 一份長期憑證才會是比較省事的寫法。**執行形態決定了
      哪一種憑證策略比較便宜**，而執行形態到 1.1 才定下來
  - **但這個提案降不到零，而剩下的那一把正是最敏感的**：Omni SA key 是 Admin 級。所以
    「Secret 被讀走會失去什麼」不因為這個提案而消失，只是從「一堆客戶叢集憑證」收斂成
    「一把可以簽出全部客戶叢集憑證的鑰匙」——**收斂了體積，沒有收斂後果**
  - **因此 1.5 依賴 `ferry133/jg-cluster-template#3`，不能先決**：#3 量出 `claudecode/claude-code`
    的 SA 綁的是 cluster-wide `cluster-admin`（已自行核對 `jg-base/.../claude-code/app/rbac.yaml`
    的 ClusterRoleBinding `claudecode-claude-code`），RBAC 純加法無 deny，所以同叢集的 `cc`
    讀得到任何 namespace 的 Secret，包含 factory 的。若 #3 的結論是「憑證不落 Secret」，
    本提案幾乎就是答案；若結論是別的方向，那把 SA key 放在哪裡就得重新談
  - **不要在 #3 定案前改寫 D1 / `design.md:145`**：把它改成任一選項的形狀，等於用文字替
    ferry133 做了選擇

## 2. Factory 執行環境（jg-base + jcom）

- [ ] 2.1 在 `jg-base` 新增 `kubernetes/apps/extras/factory/factory/`：namespace、獨立 ServiceAccount、最小權限 RBAC
  - **`extras/` 而非 `base/`**（2026-08-16 更正，`ferry133/jg-cluster-template#2`）。在 jg-base，
    `base/` 不是位置而是**發佈範圍**：每座叢集的 Flux 都指著 jg-base、`interval: 1h`、中間沒有
    逐叢集審核（`jcom/kubernetes/flux/cluster/ks.yaml:25-33` 已核）。原本的寫法會在一小時內把
    factory 的 namespace / SA / HTTPRoute 一併送到 **jg-jiahd 與 jgt-appliance**——而 factory 正是
    Omni Admin + GitHub PAT + Cloudflare 母帳號的集中點（D1、`design.md:145`），那三樣東西
    最不該在客戶 appliance 上有落腳處
  - 這不是新決定，是把 2.1 拉回本 change 自己的 design：D1 說 factory 跟著 Omni 待在 jcom，而
    Omni 本來就是以 `omni/omni` 由 `jcom/cluster.yaml:137` 選入的 extra
  - 路徑形狀取 `extras/factory/factory/`，`cluster.yaml` 寫 `factory/factory`——與 `omni/omni`
    逐字同型（namespace 名與 app 名相同），也符合 `CLAUDE.md` 的 `extras/<ns>/<app>/` 慣例
- [ ] 2.2 驗證 factory 的 SA **不是** `claudecode/claude-code/app/rbac.yaml` 那個共用 cluster-admin SA
- [ ] 2.3 驗證同叢集的 `cc` instance 無法讀取 factory 的 secret（RBAC 拒絕）
- [ ] 2.3a 驗證 factory 的資源**不存在於** jg-jiahd 與 jgt-appliance——推 jg-base 後在兩座叢集上
      確認 `namespace/factory` 未被建立。依 fleet-ops `fleet-index.md` 的規則：jg-base 的變更，
      驗收必須包含一座**不是**目標的叢集
  - ⚠️ **這一項在授權閘之後才驗得了**：它驗的是「推送之後仍然不存在」，而推 jg-base 需要
    ferry133 點頭。在「準備但不推」的範圍內它**無法被滿足**——不要因為前面幾項都綠了就把它
    當成過了
- [ ] 2.4 建立 factory 的 HelmRelease 與 HTTPRoute（`factory.janncot.com`），登入白名單只含 operator
- [ ] 2.5 驗證客戶叢集的登入身分無法登入 factory
- [ ] 2.6 設定經 ClusterIP 直連 Omni，驗證不需 port-forward 且 gRPC streaming 呼叫不出現 trailers 錯誤
- [ ] 2.7 確認容器內具備完整工具鏈（`omnictl` `gh` `cloudflared` `age` `sops` `cue` `makejinja` `task` `kubectl` `helmfile`），版本與 repo pin 一致
- [ ] 2.8 驗證 image 內不含任何憑證材料，憑證全部 runtime 注入
- [ ] 2.9 建立憑證清單文件：每項憑證的用途、範圍、blast radius、輪替方式

## 3. 工單狀態機

- [ ] 3.1 定義工單 label 詞彙（有序階段），與既有 `docs/agents/triage-labels.md` 對齊
- [ ] 3.2 實作工單建立：交付啟動時開 Issue，記錄客戶、profile、預期機器
- [ ] 3.3 實作階段推進：完成一階段即換 label，任何時刻恰有一個階段 label
- [ ] 3.4 實作進度 comment：記錄動作、外部資源識別碼、驗證證據
- [ ] 3.5 加入防護：comment 寫入前檢查不含金鑰材料
- [ ] 3.6 實作 resume：從 label 與 comment 判定已完成階段並記錄跳過了哪些
- [ ] 3.7 實作矛盾處理：記錄狀態與觀察狀態不一致時停止並升級
- [ ] 3.8 在 `monitoring/daily-check` 加入停滯工單回報（階段 + 停留時間）

## 4. Provisioning 流程

- [ ] 4.1 實作機器註冊偵測，並與開放中的工單比對
- [ ] 4.2 未匹配任何工單的機器不得自動建叢集，改為回報 operator
- [ ] 4.3 實作 Omni cluster 建立（含 `cniConfig: none` 等首次開機前必須的 patch）
- [ ] 4.4 實作由 template 建立 user repo，名稱由 `cluster_name` 決定（決定性命名）
- [ ] 4.5 實作 Cloudflare tunnel 與 DNS 建立，名稱同樣決定性
- [ ] 4.6 實作 `cluster.yaml` 推導：網路值一律來自 Omni 回報的機器實際網路狀態，不接受人工輸入
- [ ] 4.7 串接 `task configure` → commit → push
- [ ] 4.8 實作 kubeconfig 取得與 `task bootstrap:apps`
- [ ] 4.9 實作完成判定：等到 Flux reconcile **且** 常駐 agent 可達，才算完成並記錄交棒
- [ ] 4.10 為每一步實作「先查後建」，驗證重跑不產生第二個 repo / tunnel / cluster
- [ ] 4.11 實作 QUIC 封鎖的自動修復（套用 http2 transport、驗證恢復、記錄動作）
- [ ] 4.12 實作未知失敗的停止與升級（不無限重試），附診斷證據
- [ ] 4.13 實作「機器未出現」的回報：列舉可能原因而不斷言，附非技術人員可執行的現場檢查清單

## 5. 身分與憑證

- [ ] 5.0 網域流程（D11）：客戶自有網域 → NS 委派到 operator 的 Cloudflare 帳號；zone 與 token 皆在 operator 側，客戶零輸入。含 operator 代購網域的選項
- [ ] 5.0a 驗證：零輸入 profile 的 provisioning 全程不向客戶索取任何 API token 或帳號憑證
- [ ] 5.0b 驗證：交接前後 hostname 完全不變，改變的只有「哪個帳號管這個網域的 DNS」

- [ ] 5.1 依 1.2 結論實作每叢集服務身分建立
- [ ] 5.2 明確禁止任何自動化消費者帳號註冊流程（程式與 runbook 皆須寫明）
- [ ] 5.3 實作登入身分設定：常駐 agent 白名單放客戶自己的信箱，服務身分不得為可登入身分
- [ ] 5.4 實作每叢集憑證清單的產生與更新（新增/輪替/移除時同步更新）
- [ ] 5.5 實作 `age.key` escrow，並讓 escrow 未確認時 provisioning 不得標記完成
- [ ] 5.6 為每項憑證撰寫就地輪替程序；`age.key` 輪替須以 `sops updatekeys` 就地重加密

## 6. 交接

- [ ] 6.0 交接封裝除列出「持有什麼」外，須逐項記載「要用它需要什麼能力」（D12 的不對稱）——操作 Cloudflare DNS、git 與 SOPS、Omni 或 Talos client cert

- [ ] 6.1 實作 `task handover`：SOPS 重新加密至客戶公鑰、repo transfer、Cloudflare 帳號信箱、Omni 控制權（依 1.4）、模型 API 憑證、k8s 存取
- [ ] 6.2 實作部分失敗的回報：列出成功與失敗項，不得回報成功
- [ ] 6.3 實作交接封裝產出：客戶持有什麼、各自用途、遺失的後果、需要的例行動作
- [ ] 6.4 實作交接後 operator 殘留存取的撤銷；保留支援關係時須在封裝明載保留了哪些
- [ ] 6.5 在 scratch 叢集執行交接演練：由無 operator 權限者只憑封裝完成 reconcile、解密 secret、登入常駐 agent
- [ ] 6.6 依演練結果修正，重跑至通過；未通過前不得對客戶宣稱可交接

## 7. Runbook / Skill

- [ ] 7.1 撰寫 `.claude/skills/provision-customer-cluster/SKILL.md`，每步含前置條件、指令、驗證斷言、失敗分支
- [ ] 7.2 由人工照 runbook 逐步執行一次完整 provisioning，修正指令與斷言的錯誤
- [ ] 7.3 交由 factory agent 自動執行同一份 runbook，比對結果一致
- [ ] 7.4 在 `CLAUDE.md` 新增 factory agent 與交接流程章節，並移除已被 factory 取代的手動 port-forward 說明

## 8. 驗收

- [ ] 8.1 以 scratch 工單完成一次全自動 provisioning，全程無人介入
- [ ] 8.2 在流程中途強制中斷 factory agent，驗證重啟後由工單續跑且無重複外部資源
- [ ] 8.3 模擬 QUIC 封鎖，驗證自動修復成功並留下記錄
- [ ] 8.4 模擬機器未上線，驗證回報列舉可能原因且不斷言
- [ ] 8.5 第一台真實客戶以「agent 執行、人在旁看」模式交付，事後檢討工單留痕
- [ ] 8.6 回寫所有 spike 結論到 `design.md` 與相關 spec，確認無「待驗證」項目遺留

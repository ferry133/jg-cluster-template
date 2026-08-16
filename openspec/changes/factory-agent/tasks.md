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
- [x] 1.2 **由決策取消，非由調查回答**（2026-08-16，`ferry133/jg-cluster-template#5`）：帳號由
      客戶自己申請，公司不建立任何使用者——沒有 Admin SDK、沒有最小權限範圍、沒有 domain-wide
      delegation 這題。它也不只是「沒有違反 5.2」，而是讓 5.2 要禁止的那件事根本不必發生
- [x] 1.3 **同樣由決策取消**：每位客戶的 Cloudflare 帳號存在於他自己的 Google 身分之下，
      沒有母／子帳號結構要去取得資格。我先前提的「子帳號 vs 委派存取」也一併消失——**兩者皆非，
      那是客戶自己的帳號**，公司登入它
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
  - ~~不要在 #3 定案前改寫 D1 / `design.md:145`~~ → **#3 已於 2026-08-16 選定 (a)，D1 與
    Risks 首項已改寫為量測到的位置**
  - **(a) 定了 1.5 的一半，而且是往「持有」的方向定**：(a) 維持憑證放在 Kubernetes Secret，
    所以「factory 是否長期持有憑證」不再是問題——是，由決策定的。**「客戶叢集憑證用時再取」
    的提案因此降級為最佳化建議，不是待決事項**
  - **剩下的那一半被 (a) 變得更尖銳，不是更緩和**：在 (a) 之下，factory 若承擔 escrow，
    N 把客戶 `age.key` 就躺在同叢集任何 cluster-admin 主體讀得到的地方，而它們是唯一
    **沒有撤銷路徑**的憑證類別。所以 **1.5 真正要問 ferry133 的只剩一題：factory 到底要不要
    承擔 5.5 的 escrow？** 其餘都已被 (a) 或 1.1/1.4 決定
  - ⚠️ **不要把 Google 帳號那個方向寫成交接的解答**（2026-08-16 已定案為 D11，見 #5；
    這條警告因此從「先別假設」升級為「已知的缺口」，撤銷清單見 6.4）：那個模型假設
    「客戶改掉一個密碼就切斷公司存取」。在 (a) 之下它不成立——
    已簽發的 Cloudflare API token 與 Auth0 client secret 獨立於登入密碼；而 escrow 的
    `age.key` 根本不受密碼變更影響。**改密碼切斷的是取得新憑證的能力，不是已經發出去的那些。**
    交接若寫成「改密碼即完成」，那會是今天反覆出現的同一種缺陷：一個讀起來像完成的動作
  - **提案的「只有一把」還沒算到 5.5**（2026-08-16 補）：`age.key` escrow 若由 factory 承擔，
    factory 就同時是每一座客戶叢集金鑰的保管處——那時「factory 只長期持有一把憑證」是假的，
    它持有的是 **N 把客戶金鑰加上自己那把**。而 `age.key` 是備份唯一的解密能力，聚在一處的
    後果比 Omni SA key 更難收拾：SA key 可以撤銷重發，客戶的 `age.key` 撤不掉——換掉它等於
    讓既有封存全部變成沒人打得開的密文
  - 所以 1.5 要回答的其實是兩個存活期，不是一個：factory 對**客戶叢集憑證**的（可現簽，
    提案為不留存），以及 factory 對**客戶金鑰材料**的（不可現簽，因為它就是根）。
    後者在 `docs/operations/age-key-escrow.md` 的定義裡，escrow 的去處必須是「能在 appliance
    之外存活、且不與它一起失效」的地方——**factory 是不是那個地方，是設計問題不是實作細節**

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

- [ ] 5.0 網域流程（D11，2026-08-16 改寫）：客戶自有網域 → NS 委派到**以客戶 Google 帳號註冊的**
      Cloudflare 帳號。zone 與 token 仍由公司實際操作，但**帳號歸屬是客戶的**，客戶零輸入的性質不變
      （他只需要在簽約時申請 Google 帳號）。含 operator 代購網域的選項
  - 原文「zone 與 token 皆在 operator 側」已不是這個模型的形狀，勿照舊實作
- [ ] 5.0a 驗證：零輸入 profile 的 provisioning 全程不向客戶索取任何 API token 或帳號憑證
- [ ] 5.0b 驗證：交接前後 hostname 完全不變，改變的只有「哪個帳號管這個網域的 DNS」

- [ ] 5.1 依 1.2 結論實作每叢集服務身分建立
- [ ] 5.2 明確禁止任何自動化消費者帳號註冊流程（程式與 runbook 皆須寫明）
- [ ] 5.3 實作登入身分設定：常駐 agent 白名單放客戶自己的信箱，服務身分不得為可登入身分
- [ ] 5.4 實作每叢集憑證清單的產生與更新（新增/輪替/移除時同步更新）
- [~] 5.5 ~~實作~~ **descope 為員工手動動作**（2026-08-17，`ferry133/jg-cluster-template#6` 的
      追加留言）：自動化「產生、escrow、以確認為閘門」不在出貨關鍵路徑上，改由員工每次交付執行，
      步驟落在 §7.0。**閘門本身仍須存在**，只是形式從程式碼變成有記錄結果的 runbook 步驟
  - **「已確認」是兩個不同的性質，5.5 只證得了其中一個**（2026-08-16，fleet-ops 提出依賴，
    查證後結論與其敘述不同）：
    1. **金鑰同一性**——escrow 副本是一把有效的 age key，其公鑰與 `.sops.yaml` 的 `age:` 逐字
       相同。`docs/operations/age-key-escrow.md:36-50` 已經定義了做法（`age-keygen -y` 比對），
       **可自動化、逐叢集、且正好擋住它點名的失效**：被截斷的副本讀起來與好的一模一樣。
       這一項 5.5 做得到，也應該做
    2. **可還原性**——一份真的封存，用那把金鑰解得開、還原出逐表相符的資料。這是
       `deployment-profiles` 8.3，**至今未執行過**
  - 所以 fleet-ops 說「今天 confirmed 只可能是『檔案寫出來了』」是低估了：既有文件定義的檢查
    比那強。但它的核心顧慮成立——**若 5.5 的閘門叫做「escrow 已確認」而不說明確認了什麼，
    factory 就會逐台出貨蓋下一個讀起來比實際強的綠燈**，而且是自動、規模化地蓋
  - **因此依賴關係不是「5.5 等 8.3」**：性質 1 是逐叢集的、可規模化；性質 2 是**管線層級**的，
    一次證完即可（管線改了要重證）。正確的排序是——5.5 可以實作，閘門照性質 1 命名；
    **8.3 必須在第一次對外交付之前跑完一次**，因為在它跑過之前，沒有人知道這條管線產出的
    封存到底還不還得回來，而那不是任何一座叢集自己回答得了的問題
  - 若只做性質 1 而讓文案讀起來像性質 2，那正是本專案今天反覆命名的同一種缺陷：**沒有錯誤
    被當成成功**——只是這次會被刻意製造，每交付一台就一份
- [ ] 5.6 為每項憑證撰寫就地輪替程序；`age.key` 輪替須以 `sops updatekeys` 就地重加密

## 6. 交接

- [ ] 6.0 交接封裝除列出「持有什麼」外，須逐項記載「要用它需要什麼能力」（D12 的不對稱）——操作 Cloudflare DNS、git 與 SOPS、Omni 或 Talos client cert

- [ ] 6.1 實作 `task handover`：SOPS 重新加密至客戶公鑰、repo transfer、Cloudflare 帳號信箱、Omni 控制權（依 1.4）、模型 API 憑證、k8s 存取
- [ ] 6.2 實作部分失敗的回報：列出成功與失敗項，不得回報成功
- [ ] 6.3 實作交接封裝產出：客戶持有什麼、各自用途、遺失的後果、需要的例行動作
  - **加一節「怎麼自己查證公司已經沒有存取」**：因為帳號從一開始就是客戶的，他登得進 Cloudflare
    與 Auth0，看得到 token 清單與成員清單。這把 6.4 的結果從**公司宣稱**變成**客戶查得到**，
    而 6.5 的演練本來就由無 operator 權限者執行，正好驗這一節讀不讀得懂
  - 成本是一段文字，換掉的是這份設計裡最後一個「口頭承諾」
- [ ] 6.4 實作交接後 operator 殘留存取的撤銷；保留支援關係時須在封裝明載保留了哪些
  - **交接不是「客戶改密碼」這一個動作**（2026-08-16，D11 改寫的直接後果）。改密碼擋住的是
    **取得新憑證**的能力，不是已經發出去的那些。6.4 必須逐項列舉並執行：
    1. 公司建立的每一個 Cloudflare API token —— 撤銷
    2. 公司建立的每一個 Auth0 client secret 與 application —— 輪替或移除
    3. 公司加上的每一個帳號成員與救援信箱 —— 移除
    4. `sops updatekeys` 換成客戶的金鑰，並銷毀 escrow 的 `age.key` 副本——
       `age-key-escrow.md` 已要求它必須被銷毀，或明白宣告它仍然存在
  - **若交接被寫成或說成「客戶改個密碼就完成了」，那是今天反覆出現的同一種缺陷最貴的一種形式：
    一個讀起來像完成的動作。**
- [ ] 6.5 在 scratch 叢集執行交接演練：由無 operator 權限者只憑封裝完成 reconcile、解密 secret、登入常駐 agent
- [ ] 6.6 依演練結果修正，重跑至通過；未通過前不得對客戶宣稱可交接

## 7. Runbook / Skill

> **2026-08-17 起，§7 是這個 change 的重心而不是收尾**（`ferry133/jg-cluster-template#6`）。
> ferry133 決定 DNS 設定、Cloudflare 設定與 `age.key` escrow 三者皆為**交付時由員工手動執行的
> 動作**，不必為了出貨而自動化。這是排序不是放棄，日後仍可自動化。
>
> **descope 是把工作搬走，不是把工作消掉**：§4 與 5.5 少掉的每一步，都變成某個人在客戶現場、
> 有時間壓力之下要正確執行的 runbook 步驟。§7 因此**照著 §4 卸下的量長大**。把這句寫在這裡，
> 是為了讓 descope 不被讀成一次「之後再說」的淨減少。
>
> 「零 IT」一直都是**零客戶 IT**，從來不是零工作量。客戶側維持三個物理動作加一個到貨前申請的
> Google 帳號；其餘全部由員工側吸收。

- [ ] 7.0 **手動 escrow 的必要步驟與記錄**（自 5.5 descope 而來）。escrow 改由人手執行之後，
      `age-keygen -y` 的同一性檢查就是**唯一**把「檔案被複製了」和「這份副本就是那把金鑰」
      分開的東西——而 `docs/operations/age-key-escrow.md:36-50` 明說被截斷的副本讀起來與好的
      一模一樣。**沒有驗證的手動步驟，比 5.5 原本要建的閘門更弱**，所以它必須是 runbook 裡
      一個有記錄結果的必做步驟，而不是一句提醒
  - 記錄的內容要是「比對過、公鑰逐字相同」，不是「已 escrow」——後者正是 `jgt-appliance` 現在
    宣告 `age_key_escrowed: true` 的依據，而那份宣告至今沒有任何人查證過
- [ ] 7.1 撰寫 `.claude/skills/provision-customer-cluster/SKILL.md`，每步含前置條件、指令、驗證斷言、失敗分支
  - descope 之後這份 runbook 必須涵蓋：DNS 設定（三種做法見 `docs/operations/router-dns.md`）、
    以客戶 Google 帳號註冊 Cloudflare 與 Auth0（D11）、以及 7.0 的 escrow 與其驗證
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

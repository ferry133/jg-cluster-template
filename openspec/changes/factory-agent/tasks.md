> **執行順序：Phase 2 —— 盡可能自動化**（2026-08-20，見 `openspec/SEQUENCING.md`）
>
> 手工跑一次是為了讓 runbook 的指令與斷言先被人校正過，不是終點：7.2（人工照 runbook
> 跑完）之後緊接 7.3（交給 agent 跑同一份，比對結果一致），中間不要停。
>
> 範圍：§2、§3、§4、§5（扣掉 5.0b / 5.5）、§7（扣掉 7.0）、§8 的 8.1–8.4 與 8.6。
>
> **與 Phase 1 的關係**：大致獨立、可重疊。唯一的方向性依賴是 `zero-it-onboarding`
> 5.1–5.3 餵給 4.1——機器不會自己回連，就沒有東西可以偵測。
>
> **交接延後**（2026-08-20 裁定）：5.0b、5.5、7.0、§6 全部。8.5 要有真實客戶才跑得了。
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

- [x] 1.5 **由決策關閉（2026-08-17）：「factory doesn't do escrow. employee action.」**——ferry133，
      `ferry133/jg-cluster-template#6`。factory 長期持有的憑證為三把：Omni SA、GitHub PAT、
      Cloudflare，**不持有任何客戶金鑰材料**
  - 這一題原本是明著問的（見下方推導），沒有讓它由 descope 推論出來——差別在於「沒有人這樣
    決定過，只是沒人反對」與「他決定了」，而前者在半年後讀起來一模一樣
  - **三把都是可撤銷、可重發的**。這正是先前擔心的那條線的另一邊：`age.key` 沒有撤銷路徑，
    而它現在不在 factory 手上
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

## 2. Factory 執行環境（jg-base + jcom）  **[P2]**

- [x] 2.1 在 `jg-base` 新增 `kubernetes/apps/extras/factory/factory/`：namespace、獨立 ServiceAccount、最小權限 RBAC
  - **已在 `jg-base` `main`**（2026-08-17 於 `origin/main` 實測 tree，非依報告）：`3d54330`
    feat(factory) 建 `namespace.yaml` 與 `app/rbac.yaml`，目錄現含 `ks.yaml`、
    `kustomization.yaml`、`app/kustomization.yaml`、`README.md`。**尚無 HelmRelease 與
    HTTPRoute**——那是 2.4，見該項
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
- [ ] 2.1a 在 `jcom/cluster.yaml` 的 `extras:` 加入 `factory/factory`，`task configure --yes` 後 push
  - **本節標題寫「jg-base + jcom」，但在此之前每一項都只動 jg-base**（2026-08-17 補）。
    實測 `jcom/cluster.yaml` 的 `extras:` 清單只有 `ingress-nginx/ingress-nginx`、
    `network/cloudflare-tunnel-lan`、`default/echo`、`default/homebridge`、`default/mqtt`、
    `claudecode/postgres`、`freepbx/freepbx`、`omni/omni`——**沒有 `factory/factory`**
  - 少了這一步，jg-base 推完之後 factory **不存在於任何叢集**，包含它該在的 jcom
  - **這不會削弱 2.3a**（本項初稿曾這樣寫，是錯的）。jg-jiahd 與 jgt-appliance 本來就永遠
    不會選 `factory/factory`，所以它們的 NotFound 測的正是「`extras/` 的 app 不會流到沒選它的
    叢集」——若當初放在 `base/`，兩座都會有，因為 `base/` 是無條件下發的。jcom 尚未選入
    只表示 factory 還沒被部署，不表示 2.3a 量不到東西
  - 同樣在授權閘之後：推 jcom 會在一小時內生效
- [x] 2.2 驗證 factory 的 SA **不是** `claudecode/claude-code/app/rbac.yaml` 那個共用 cluster-admin SA
  - **成立**（2026-08-17 讀 `jg-base` `origin/main` 的 `extras/factory/factory/app/rbac.yaml`）：
    `ServiceAccount/factory` 於 `namespace: factory`，**沒有 Role、RoleBinding 或 ClusterRole**，
    且 `automountServiceAccountToken: false`。與 `claudecode` 的 `ServiceAccount/claude-code`
    （綁 `ClusterRole/cluster-admin`）是不同主體
  - **但這只約束 factory 能做什麼，不約束誰能讀 factory**——見 2.3
  - ⚠️ **目前為真的是「宣告」，不是「使用」**：2.4 被卡住，所以還沒有任何 workload 用到
    `ServiceAccount/factory`。之後補的 Deployment 若漏了 `serviceAccountName: factory`，
    會落到 ns `factory` 的 `default` SA，本項就**在打勾狀態下悄悄變成假的**。斷言寫進 2.4
- [ ] 2.3 驗證同叢集的 `cc` instance 無法讀取 factory 的 secret（RBAC 拒絕）
  - ⚠️ **這一項已經驗過了，答案是否定的，所以它不該被打勾。** `jg-base`
    `extras/factory/factory/README.md` 記著在 jcom 上的實測：
    `kubectl auth can-i '*' '*' --as=system:serviceaccount:claudecode:claude-code --all-namespaces`
    回 `yes`。`cc` 與 `im` 共用那個綁 cluster-admin 的 SA，而 **Kubernetes RBAC 是可加的、
    沒有 deny**，所以「獨立 namespace + 最小權限 SA」對這題完全不生效
  - 換叢集也不解決：`claudecode` 是 base app，每座叢集都有一個同居的 cluster-admin
  - **ferry133 已決定接受**（`ferry133/jg-cluster-template#3`，2026-08-16，經 fleet-ops 轉達）。
    後續可能另開一座叢集跑 IM instances，該選項是**延後而非否決**
  - 因此本項的狀態不是「未做」也不是「已通過」，而是**做了、結論相反、風險被接受**。
    打勾會讓掃 checkbox 的讀者得到「factory 的 secret 有 RBAC 保護」這個錯誤結論——正是
    2.3a 自己警告的「因為旁邊都綠了就跟著綠」。要結案請改寫本項的斷言，不要改它的方框
  - 連帶：README 那份憑證清單因此**就是控制本身**（#3 之後沒有其他緩解措施），所以清單漏掉
    任何一項就不是「已接受的風險」而是「沒被記錄的風險」，兩者從外面看一模一樣
- [x] 2.3a 驗證 factory 的資源**不存在於** jg-jiahd 與 jgt-appliance——推 jg-base 後在兩座叢集上
      確認 `namespace/factory` 未被建立。依 fleet-ops `fleet-index.md` 的規則：jg-base 的變更，
      驗收必須包含一座**不是**目標的叢集
  - **通過**（2026-08-17，本 session 於兩座叢集各自實測，非採信報告）：

    | 叢集 | `ns/factory` | 正對照 | jg-base GitRepository |
    |---|---|---|---|
    | jg-jiahd | `NotFound` | `claudecode` / `flux-system` 皆 `Active` | READY `main@sha1:66260d8` |
    | jgt-appliance | `NotFound` | `claudecode` / `flux-system` 皆 `Active` | READY `main@sha1:66260d8` |

  - **2026-08-17 稍晚重驗，而且現在是更強的測試**：jg-base `main` 已前進到 `7341965`
    （merge `84a0a0e`，2.4 的 workload）。jg-jiahd 已抓到該 revision 且 `ns/factory` 仍
    `NotFound`——所以現在驗的是「連 HelmRelease 與 Deployment 都在的那個 commit 也沒有外洩」，
    不再只是 namespace 與 SA
  - ⚠️ **上表的 `66260d8` 在記錄後幾小時內就過期了。** 這本身是個提醒：**一個註明了 commit
    的量測，它的有效期就到那個 commit 不再是 head 為止**；沒有重驗就引用它，與沒有量過的
    差別只在於它看起來有出處
  - **關鍵在第三欄，不在第一欄。** 「隔離成功」與「Flux 根本沒動」produce 一模一樣的
    `NotFound`。兩座叢集都已經把**含有 `extras/factory/factory/` 的那個 commit** 抓下來
    （`66260d8` 即 `jg-base` `origin/main` 的 head，該 tree 內確有該目錄），且仍然沒有
    `namespace/factory`——這才把良性解釋與惡性解釋分開
  - 因此 2.1 的「`extras/` 而非 `base/`」是**被量出來的**，不是被論證出來的
  - ⚠️ 原註記「本項在授權閘之後才驗得了、在準備但不推的範圍內無法被滿足」**已不適用**：
    jg-base 那一側早就推了。這句警告仍然對 2.1a（jcom 選入）與 2.4 之後的驗收有效，
    但它擋不住 2.3a 本身
- [ ] 2.4 建立 factory 的 HelmRelease 與 HTTPRoute（`factory.janncot.com`），登入白名單只含 operator
  - **形狀已定，image ref 未定**（`ferry133/jg-cluster-template#4`，ferry133 於 2026-08-17 回答
    兩題）：image 是 **k8scc variant**——既有的 `ghcr.io/ferry133/claude-code` 加上 1.1 那個
    Go/COSI watch；`factory.janncot.com` **確實**出結一個 ttyd terminal，前面擋一份 operator-only
    白名單
  - image 工作路由到 **`ferry133/k8scc#1`**（該 repo 擁有 Dockerfile）。該 issue 刻意寫成
    **credential-blind**：k8scc 是 public repo，所以那邊只放建置需求，不放 factory 集中了什麼。
    憑證清單留在 2.9
  - **卡在 k8scc#1 回報 `image.repository` / `image.tag`，不是卡在設計。** 2026-08-17 實測
    `ferry133/k8scc#1` 仍 OPEN 且無留言，尚未回報
  - 這也解掉 `jg-base` README「Not yet decided」記的那個缺口——「§2 假設了一個沒有任何一節
    生產的 artifact」。現在有 k8scc#1 生產它了
  - **Deployment 必須明寫 `serviceAccountName: factory`**，並把這一行納入本項驗收。
    漏掉它不會報錯：pod 會拿 ns `factory` 的 `default` SA 跑起來，看起來一切正常，而 2.2
    在維持打勾的狀態下變成假的。同時保留 `automountServiceAccountToken: false` 的效果
- [ ] 2.5 驗證客戶叢集的登入身分無法登入 factory
  - 卡在 2.4：白名單還不存在，沒有東西可以被拒絕。**現在「登不進去」是因為沒有服務，
    不是因為白名單生效**——這兩者的觀測結果相同，別把前者當成後者
- [ ] 2.6 設定經 ClusterIP 直連 Omni，驗證不需 port-forward 且 gRPC streaming 呼叫不出現 trailers 錯誤
  - 卡在 2.4：目前 `extras/factory/factory/` 只有 namespace 與 SA，**沒有 workload**，
    沒有任何 pod 可以發出這個 gRPC 呼叫。本項無法在推送與 2.4 之前被驗證
- [x] 2.7 確認容器內具備完整工具鏈（`omnictl` `gh` `cloudflared` `age` `sops` `cue` `makejinja` `task` `kubectl` `helmfile`、**以及 1.1 那個 COSI watch binary**），版本與 repo pin 一致
  - **清單本身站得住，只多一項**（`#4`，2026-08-17）。1.1 排除的是 **`omnictl` 承載 watch**
    ——該 CLI 沒有 watch 旗標——**不是排除 `omnictl` 本身**。§4 仍然整套用得到：4.5 cloudflared、
    4.7 `task configure` → commit → push、4.8 kubeconfig + `task bootstrap:apps`
  - 7.1 要的是 `.claude/skills/provision-customer-cluster/SKILL.md`，7.3 把同一份 runbook 交給
    factory agent 執行——會執行 Claude Code skill 的東西就是一個 Claude Code instance，
    這也是 image 取 k8scc variant 的理由
  - **通過**（2026-08-17，image 已交付：`ghcr.io/ferry133/claude-code:factory-170830f`）。
    本 session 自行量到的部分：GHCR manifest digest `sha256:b10e9ed5…`（與 jg-base 回報相同）、
    amd64 manifest **28 層**、label `org.opencontainers.image.revision=170830fb…`
  - **版本與 repo pin 一致——逐項比對過**（`k8scc` `Dockerfile` 的 `ARG` vs 本 repo `.mise.toml`）：
    gh 2.87.3、cloudflared 2026.2.0、age 1.3.1、sops 3.12.1、cue 0.15.4、makejinja 2.8.2、
    task 3.48.0、helmfile 1.3.2 全部相符。**kubectl 與 talosctl 有兩組 ARG 是刻意的**：
    `KUBECTL_VERSION=v1.36.0` 給 base image，factory stage 用的是
    `FACTORY_KUBECTL_VERSION=v1.35.2` / `FACTORY_TALOSCTL_VERSION=v1.13.8`（`Dockerfile:295,297`），
    與本 repo 的 `kubectl = 1.35.2` / `siderolabs/talos = 1.13.8` 完全相同。`omnictl v1.8.1`
    在 mise 沒有對應 pin，無從比對
  - `omni-machine-watch` 存在且在 build 階段被實際執行過（`Dockerfile:411-415`，以「缺 endpoint／
    缺 SA key」的預期錯誤字串當作正向訊號，不是只看 exit code）
  - **驗證邊界照實寫**：以上是讀 `170830f` 那個 commit 的 `Dockerfile` 與 GHCR metadata 得到的。
    本機沒有 docker，**沒有在 image 裡實跑過任何一支 binary**。「image 內的 binary 就是這些版本」
    是從 revision label 對得上 Dockerfile 推出來的，不是量出來的
- [ ] 2.7a 讓「版本與 repo pin 一致」變成會失敗的斷言，而不是一次性比對
  - **2.7 今天為真，而且沒有任何東西讓它保持為真。** `k8scc/Dockerfile` 的 ARG 與本 repo
    `.mise.toml` 是兩個 repo 裡的兩份數字，哪一邊先 bump 都不會有人失敗——2.7 會在打勾狀態下
    悄悄變假
  - 而且 build 內的 `verify` **只印版本、不比對**：它只有在指令 exit 非零時才失敗
    （`Dockerfile:377-387`）。十支工具裡**只有 makejinja 真的斷言了版本**
    （`installed = MAKEJINJA_VERSION`，`Dockerfile:357-361`）——正因為它是唯一被 `--version`
    騙過的那一支。其餘九支「版本正確」靠的是版本號寫在下載 URL 裡，即**由建構方式保證**，
    而 makejinja 那件事正是「由建構方式保證」在另一個方向上失效的實例
  - 小處但屬同一類：`UV_PYTHON_VERSION=3.14` 而 `.mise.toml` 寫 `python = "3.14.3"`。
    Dockerfile 註解說它是「driven repo 所 pin 的 Python 版本」，但一個是 minor、一個是 patch，
    build 時解析到哪個 3.14.x 不固定
  - 這一項屬 `ferry133/k8scc`（它擁有 Dockerfile），本項只留指標
- [x] 2.8 驗證 image 內不含任何憑證材料，憑證全部 runtime 注入
  - **通過，由 `jg-base` 實測**（2026-08-17）：拉 digest `sha256:b10e9ed5…`（本 session 獨立
    向 GHCR 確認過此 digest 與 28 層）並掃過**全部 28 層**
  - **兩個必須寫進測試本身的要求**，否則這個檢查下次會退化：
    1. **必須有 upstream-binary 排除清單。** 掃描在 `/usr/local/bin/age-keygen` 裡找到一個
       完整長度的 `AGE-SECRET-KEY-1` 字串——那支 binary 與上游 age v1.3.1 checksum 相同，
       所以那個字串存在於每一份下載副本裡。**紅燈，而且是假的。** 一個每次都狼來了的檢查
       會被靜音，而被靜音的檢查在外面看起來與「有覆蓋」一模一樣
    2. **必須掃 layer，不能掃壓平後的檔案系統。** 壓平之後，這個乾淨的 image 與一個
       「某層寫入憑證、後續層刪掉」的洩漏 image 會給出相同結果
  - 這兩點與 2.7a 的 makejinja 是同一個缺陷的兩端：**綠的可能是假的，紅的也可能是假的，
    出問題的是檢查而不是被檢查的東西**
- [x] 2.9 建立憑證清單文件：每項憑證的用途、範圍、blast radius、輪替方式
  - **已在 `jg-base` `extras/factory/factory/README.md`**（2026-08-17 讀 `origin/main` 確認，
    最後一次更動 `66260d8`）。三項憑證各有用途／範圍／blast radius／輪替方式的表格：
    Omni Admin SA、GitHub PAT、Cloudflare 母帳號 token
  - 另記兩件不在原始要求裡但屬於同一份清單的事：**`age.key` 是被決定排除而非遺漏**
    （`#6`，2026-08-17「factory doesn't do escrow. employee action.」），以及
    **檢查憑證要比對材料而非標籤**——`GET /zones` 回 HTTP 200 加空陣列、名稱對但 zone 是
    另一個帳號裡的 `moved` zone，兩種失效都能通過「API 收下這個 token 嗎」這種檢查
  - 客戶叢集 kubeconfig 的存活期仍未決（`design.md:167`），是清單裡唯一還開著的憑證問題

## 3. 工單狀態機  **[P2]**

> **§3 實作於 `scripts/delivery-ticket.py`，詞彙與理由寫在 `docs/agents/delivery-tickets.md`**
> （2026-08-17）。做成會 exit 1 的腳本而不是 runbook 條文，因為這裡每一條保證都是「agent
> 必須記得」的那種——散文寫的規則會被遵守，直到它真正重要的那一次。

- [x] 3.1 定義工單 label 詞彙（有序階段），與既有 `docs/agents/triage-labels.md` 對齊
  - 六個有序階段 `delivery/intake → awaiting-hardware → provisioning → verifying →
    handover → done`，外加**不是階段**的 `delivery/blocked`（與階段標籤並存，保留階段讓
    resume 知道停在哪）
  - 與 triage-labels 的關係寫明為**兩套詞彙、兩種對象、不混用**：triage 標籤問的是「誰該
    處理這份回報」，階段標籤追的是「一件已經完全指定的工作進行到哪」。`delivery/` 前綴就是
    為了讓兩者永遠不會在標籤清單裡撞名
- [x] 3.2 實作工單建立：交付啟動時開 Issue，記錄客戶、profile、預期機器
- [x] 3.3 實作階段推進：完成一階段即換 label，任何時刻恰有一個階段 label
  - 兩個階段標籤並存時**拒絕並且不自動修**：哪一個才對是關於世界的問題，不是關於標籤的問題，
    挑一個等於把猜測寫成事實
  - 跳階段要 `--force`。跳階段正是「交付走到 handover 而 verifying 從未跑過」的成因
- [x] 3.4 實作進度 comment：記錄動作、外部資源識別碼、驗證證據
- [x] 3.5 加入防護：comment 寫入前檢查不含金鑰材料
  - 涵蓋 age key、Cloudflare token、GitHub PAT、PEM、JWT，以及 `cluster.yaml` 的已知憑證欄位
  - **對 `field: ""`、`"<your-token>"`、`"${CF_TOKEN}"`、`CHANGE-ME` 刻意保持安靜。**
    第一版三個都誤報——那正是正確文件長的樣子，而**一個對範例狂叫的守衛會被關掉，
    被關掉的守衛從外面看起來與通過一模一樣**
- [x] 3.6 實作 resume：從 label 與 comment 判定已完成階段並記錄跳過了哪些
  - 輸出明寫它讀的是標籤，也就是**被宣稱的狀態**而非真實狀態；崩潰後要先重跑當前階段的斷言，
    因為最可能做到一半的就是當時進行中的那個階段
- [x] 3.7 實作矛盾處理：記錄狀態與觀察狀態不一致時停止並升級
  - 停下來而不調和：「推進了但工作沒完成」與「完成了但沒記錄」需要相反的修正，而從工單本身
    看兩者一模一樣
- [ ] 3.8 在 `monitoring/daily-check` 加入停滯工單回報（階段 + 停留時間）
  - **屬 `jg-base`**（`ferry133/jg-base#8`），落在 `monitoring/daily-check`。本 repo 只留指標
- [ ] 3.9 對 scratch 工單實跑一次 3.2–3.7
  - ⚠️ **3.2–3.7 的純邏輯有單元測試（22 個 scanner 案例、階段轉移表、雙標籤拒絕全數通過），
    但所有呼叫 `gh` 的路徑一次都沒有真的執行過。** 這與 7.2 之於 runbook 是同一件事，
    也與本 change 今天反覆記錄的那條一致：**寫完不等於對，兩次被抓到的錯都是執行抓到的。**
    不要因為 3.2–3.7 打了勾就當作它跑得起來

## 4. Provisioning 流程  **[P2]**

> 🚩 **§4 排在 §7.2 之後**（2026-08-17，fleet-ops 提議，本 repo 同意並補上自己的證據）。
> §4 是把 provisioning 程序自動化，而 §7.2 是那份程序**第一次被人真的執行**。在它被執行過
> 之前自動化它，等於把一份沒有人驗證過的程序放大；而 7.3 的存在就是拿 agent 的執行去比對
> 人的執行，那需要人的執行先存在。
>
> **證據來自本 repo 今天自己犯的兩次錯，兩次都不是覆查抓到的：** runbook 初稿斷言
> `cluster.yaml` **已被** commit（在 public repo、對一個含全 fleet Auth0 client secret 的檔案），
> 是另一個 session 轉來的一個事實撞出來的；idempotence 修正的第一版比對是死碼、永遠不會執行，
> 是測試抓到的。**兩次都由執行抓到，沒有一次由重讀抓到。**
>
> 因此 §4 各項維持未開始，先做 7.1a（讓 runbook 的斷言可執行）與 7.2。這不是延後 §4，
> 是拒絕在沒有基準的情況下自動化。

- [ ] 4.1 實作機器註冊偵測，並與開放中的工單比對
- [ ] 4.2 未匹配任何工單的機器不得自動建叢集，改為回報 operator
- [ ] 4.3 實作 Omni cluster 建立（含 `cniConfig: none` 等首次開機前必須的 patch）
- [ ] 4.4 實作由 template 建立 user repo，名稱由 `cluster_name` 決定（決定性命名）
  - **建完要清掉模板自己的開發產物**（2026-08-22，7.2 首次實跑發現）：GitHub template 會
    複製 template repo 裡**每一個被追蹤的檔案**，於是新的 cluster repo 帶著
    jg-cluster-template 自己的五個 openspec change——53 個檔、588K 的提案、決策與事故
    紀錄，而 cluster repo 是 public 且以客戶命名
  - 不只是雜訊：它構成**第二份副本**，而 fleet 規則明寫「其他 repo 只留連結指標，不重複
    追蹤——第二份副本必然分岔，而被照著執行的往往是錯的那一份」。template 每產生一個
    repo 就複製一次，分岔是必然不是風險
  - **決定性命名的規則本身也還沒寫下來**。D4 要求名稱「由工單可推導」，但沒有定義推導式。
    7.2 當場由既有叢集反推出慣例並由 ferry133 定案：`jg-<網域去掉點號>`
    （`janncot.cc` → `jg-janncotcc`），repo 與 tunnel 同名。**Omni 不接受點號**
    （`name should only contain letters, digits, dashes and underscores`，實測），
    所以規則必須產出無點號的字串——這是規則的約束，不是巧合
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

- [ ] 5.0 **[P2]** 網域流程（D11，2026-08-16 改寫）：客戶自有網域 → NS 委派到**以客戶 Google 帳號註冊的**
      Cloudflare 帳號。zone 與 token 仍由公司實際操作，但**帳號歸屬是客戶的**，客戶零輸入的性質不變
      （他只需要在簽約時申請 Google 帳號）。含 operator 代購網域的選項
  - 原文「zone 與 token 皆在 operator 側」已不是這個模型的形狀，勿照舊實作
- [ ] 5.0a **[P2]** 驗證：零輸入 profile 的 provisioning 全程不向客戶索取任何 API token 或帳號憑證
- [ ] 5.0b **[延後：交接]** 驗證：交接前後 hostname 完全不變，改變的只有「哪個帳號管這個網域的 DNS」

- [ ] 5.1 **[P2]** 依 1.2 結論實作每叢集服務身分建立
- [ ] 5.2 **[P2]** 明確禁止任何自動化消費者帳號註冊流程（程式與 runbook 皆須寫明）
- [ ] 5.3 **[P2]** 實作登入身分設定：常駐 agent 白名單放客戶自己的信箱，服務身分不得為可登入身分
- [ ] 5.4 **[P2]** 實作每叢集憑證清單的產生與更新（新增/輪替/移除時同步更新）
  - **照 `jg-base` `extras/factory/factory/README.md:21-25` 的五欄形狀，不要再發明第二種**
    （2026-08-17）：憑證 / 用途 / 範圍 / blast radius / 輪替方式。那份已經是活的，兩種形狀
    並存必然分岔，而被照著讀的往往是舊的那份
  - 清單要能回答的不只是「有哪些」：`README.md` 那份的價值有一半來自**明寫被排除的東西**
    （`age.key` 是決策排除而非遺漏）——**沒有的那一列與被考慮過才拿掉的那一列，從外面看
    一模一樣**
- [~] 5.5 **[延後：交接]** ~~實作~~ **descope 為員工手動動作**（2026-08-17，`ferry133/jg-cluster-template#6` 的
      追加留言）：自動化「產生、escrow、以確認為閘門」不在出貨關鍵路徑上，改由員工每次交付執行，
      步驟落在 §7.0。**閘門本身仍須存在**，只是形式從程式碼變成有記錄結果的 runbook 步驟
  - ⚠️ **這個 descope 有一半沒有被回答，寫下來以免它悄悄消失**：決策說的是「誰執行 escrow」，
    沒有說「還有沒有東西為它把關」。5.5 的價值從來不是 escrow 本身，是**escrow 未確認就不准把
    provisioning 標記為完成**那道拒絕。改成手動之後，那道閘從機器檢查降級為 runbook 條目——
    **這是一次真實的削弱，應該被寫成削弱，而不是隨著實作一起不見**
  - **決定（ferry133，2026-08-17）：保留，且取三種形式中最強的一種。** 員工把 escrow 副本
    跑 `age-keygen -y` 的輸出記下來；factory 在 4.9 拿它與該叢集 `.sops.yaml` 的 `age:`
    recipient 比對，**不符或空白就拒絕把交付標記為完成**，並回報差異
  - ⚠️ **這道閘擋不住什麼，寫在它旁邊而不是底下**：它擋不住有人直接從 `.sops.yaml` 把公鑰
    複製過來、而不是從 escrow 副本推導出來。那是**蓄意造假**，與這道閘要防的疏漏是不同的
    威脅；能驗證那份副本本身的只有 8.3。**一道被記載得比實際更強的閘門，會被信任去做它做不到
    的事**——這正是今天在別人文件裡反覆抓到的那種缺陷，不該由自己的文件再犯一次
  - 以下為決定前的意見，保留因為它是這道閘留下來的理由：**那道閘值得以縮小的形式保留。** factory 仍然負責判定交付完成
    （4.9），所以它可以繼續拒絕在「escrow 結果尚未記錄」時標記完成——**由機器把關一份由人
    產生的產物**，成本近乎零，而它擋住的正是最容易發生的那種失敗：事情做了、沒記錄，或根本
    沒做、但沒有人會發現。已請 fleet-ops 以獨立問題送給 ferry133，不當作本次 descope 的附帶品
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
- [ ] 5.6 **[P2]** 為每項憑證撰寫就地輪替程序；`age.key` 輪替須以 `sops updatekeys` 就地重加密

## 6. 交接  **[延後：交接]**

- [ ] 6.0 **[延後：交接]** 交接封裝除列出「持有什麼」外，須逐項記載「要用它需要什麼能力」（D12 的不對稱）——操作 Cloudflare DNS、git 與 SOPS、Omni 或 Talos client cert

- [ ] 6.1 **[延後：交接]** 實作 `task handover`：SOPS 重新加密至客戶公鑰、repo transfer、Cloudflare 帳號信箱、Omni 控制權（依 1.4）、模型 API 憑證、k8s 存取
- [ ] 6.2 **[延後：交接]** 實作部分失敗的回報：列出成功與失敗項，不得回報成功
- [ ] 6.3 **[延後：交接]** 實作交接封裝產出：客戶持有什麼、各自用途、遺失的後果、需要的例行動作
  - **加一節「怎麼自己查證公司已經沒有存取」**：因為帳號從一開始就是客戶的，他登得進 Cloudflare
    與 Auth0，看得到 token 清單與成員清單。這把 6.4 的結果從**公司宣稱**變成**客戶查得到**，
    而 6.5 的演練本來就由無 operator 權限者執行，正好驗這一節讀不讀得懂
  - 成本是一段文字，換掉的是這份設計裡最後一個「口頭承諾」
- [ ] 6.4 **[延後：交接]** 實作交接後 operator 殘留存取的撤銷；保留支援關係時須在封裝明載保留了哪些
  - **交接不是「客戶改密碼」這一個動作**（2026-08-16，D11 改寫的直接後果）。改密碼擋住的是
    **取得新憑證**的能力，不是已經發出去的那些。6.4 必須逐項列舉並執行：
    1. 公司建立的每一個 Cloudflare API token —— 撤銷
    2. 公司建立的每一個 Auth0 client secret 與 application —— 輪替或移除
    3. 公司加上的每一個帳號成員與救援信箱 —— 移除
    4. `sops updatekeys` 換成客戶的金鑰，並銷毀 escrow 的 `age.key` 副本——
       `age-key-escrow.md` 已要求它必須被銷毀，或明白宣告它仍然存在
    5. **任何曾經被 commit 過的憑證：一律輪替，不是刪除**（2026-08-17 新增，由當日實測而來）。
       `chore: untrack sensitive config files` 讀起來完全像一次修復，實際上只讓下一個 clone
       在 tip 看不到那個檔案，既有的每一份 clone、fork 與快取都還握著那個值。實測：
       `config.gen/cluster.yaml` 在 jg-jiahd 留下 **11 份帶 token 的副本、8 個相異 token 值**，
       jcom 另有 2 份，兩個 repo 都是 public
  - **交接前必須確認洩漏路徑本身已經關上，否則輪替只是產生下一份公開副本。** 那 8 個相異值
    不是 8 次疏忽，是 8 次盡責的輪替沿著同一條沒關的路徑送出去。而「路徑關上了」不能用
    `git check-ignore` 判斷——它量的是你當下這台機器：jg-jiahd 的 `.gitignore` **根本不在
    `HEAD` 裡**（`~/.gitignore_global:3` 忽略 `.gitignore` 自身，所以它進不了 `git add`），
    `check-ignore` 卻回報一切正常。要問的是 `git ls-files --error-unmatch .gitignore`。
    `jg-modules` 同樣未追蹤。**做法見 `docs/operations/provision-customer-cluster.md`**
  - ⚠️ 此項在 2026-08-17 由 ferry133 決定**延後處理、非已修復**；擁有者是 jg-jiahd 與 jcom，
    不是本 repo。這裡記的是交接的要求，不是那件事的追蹤紀錄
  - **若交接被寫成或說成「客戶改個密碼就完成了」，那是今天反覆出現的同一種缺陷最貴的一種形式：
    一個讀起來像完成的動作。**
- [ ] 6.5 **[延後：交接]** 在 scratch 叢集執行交接演練：由無 operator 權限者只憑封裝完成 reconcile、解密 secret、登入常駐 agent
- [ ] 6.6 **[延後：交接]** 依演練結果修正，重跑至通過；未通過前不得對客戶宣稱可交接

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

- [ ] 7.0 **[延後：交接]** **手動 escrow 的必要步驟與記錄**（自 5.5 descope 而來）。escrow 改由人手執行之後，
      `age-keygen -y` 的同一性檢查就是**唯一**把「檔案被複製了」和「這份副本就是那把金鑰」
      分開的東西——而 `docs/operations/age-key-escrow.md:36-50` 明說被截斷的副本讀起來與好的
      一模一樣。**沒有驗證的手動步驟，比 5.5 原本要建的閘門更弱**，所以它必須是 runbook 裡
      一個有記錄結果的必做步驟，而不是一句提醒
  - **2026-08-17 之後，這條記錄就是驗證的全部**（而不是機器閘門之外的補充）：1.5 定案為
    factory 完全不碰 escrow，所以在「escrow 結果」這份記錄之外，沒有第二個東西能分辨
    真正做過的 escrow 與宣稱做過的 escrow
  - 記錄的內容要是「比對過、公鑰逐字相同」，不是「已 escrow」——後者正是 `jgt-appliance` 現在
    宣告 `age_key_escrowed: true` 的依據，而那份宣告至今沒有任何人查證過
  - **已寫成 runbook 的 Step 0**（2026-08-17）：含逐字比對指令、要照抄的記錄格式（明寫
    「compared, public halves match verbatim」而非「escrowed」）、以及兩條失敗分支。刻意排在
    第一步而不是流程順位上的位置，因為它是唯一沒有第二次機會、也沒有機器後盾的步驟。
    **本項要等 7.2 真的照著跑過一次才算完成**，寫下來不等於驗證過
- [x] 7.1 撰寫 `.claude/skills/provision-customer-cluster/SKILL.md`，每步含前置條件、指令、驗證斷言、失敗分支
  - descope 之後這份 runbook 必須涵蓋：DNS 設定（三種做法見 `docs/operations/router-dns.md`）、
    以客戶 Google 帳號註冊 Cloudflare 與 Auth0（D11）、以及 7.0 的 escrow 與其驗證
  - **已建立**（2026-08-17）。六個步驟：Step 0 escrow、1 客戶 Google 帳號、2 網域／Cloudflare／
    Auth0、3 叢集與 repo、4 pin LAN 位址後才設 router DNS、5 交付前檢查表。三項都涵蓋了
  - **開頭放「先讀這個」**，把 2026-08-17 那六個實例收斂成三條適用於每一步的規則：優先斷言
    checksum／digest／distribution metadata 而非工具的自述版本；**相信任何否定結果之前先證明
    自己問對了對象**（每個讀「不存在」的斷言都配一個正對照）；記下比對了什麼而不是結論
  - **只連結不複述**（`CLAUDE.md`）：部署機制指向 `docs/deploy/manual.md` 的 Stage，DNS 三種
    做法指向 `docs/operations/router-dns.md`，escrow 政策指向
    `docs/operations/age-key-escrow.md`。runbook 只補這些文件沒有的東西——前置條件、斷言、
    失敗分支，以及 descope 之後落到人身上的那些動作
  - **`cluster.yaml` 永不 commit 寫成獨立小節**（2026-08-17，這些 repo 是**刻意公開**的）。
    初稿把這條寫反了——寫成「斷言 `cluster.yaml` 已被 commit」，那會在一個 public repo 裡
    要求 operator 確認一份含**全 fleet 共用** Auth0 client secret 的明文檔進了 git。
    來源是誤讀 §2 缺陷表的那一列：那一列講的是「如何正確驗證它的**不存在**」
    （`git log --all`，而非只看 HEAD），不是要它存在。已改為斷言仍被 ignore、
    `git log --all` 為空，並附「若印出任何東西就停止交付、先輪替憑證」的分支
  - ⚠️ **這份 runbook 本身就是「一份全部由人執行、背後沒有東西的檢查清單」**，所以它繼承了
    自己在講的那個缺陷。寫完不等於對——7.2 存在的理由就是這個
  - **正本落在 `docs/operations/provision-customer-cluster.md`，不是本項標題寫的那個路徑。**
    `.claude/` 在每個 cluster repo 都被 gitignore（本 repo `.gitignore:16`，jg-base 與
    jg-jiahd 同樣 0 個 tracked 檔案），寫在那裡等於只存在於一台機器上——正是這份 runbook
    自己在講的失效。`.claude/skills/provision-customer-cluster/SKILL.md` 保留為**指標**，
    不重複內容
  - **這個路徑選擇已定案，不是待決事項**（ferry133，2026-08-17）：**skill 的散佈是一件獨立的
    工作，與 repo 的散佈無關**，因此既不是 `.gitignore` 的政策決定，也不是 §7 的前置條件。
    本項唯一的要求是產出要進得了 git，`docs/operations/` 已經滿足；skill 檔維持為指標即可。
    該獨立工作記在 `fleet-ops/routing-log.md`（`3fa75e3`），目前無擁有者也無人需要它
  - 寫在這裡是為了讓下一個發現 `.claude/` 被 gitignore 的人**不要把它當成新問題重開一次**
- [x] 7.1a 為 runbook 的斷言補上機器可執行的版本（可行的那些）
  - Step 2 的 Cloudflare zone／delegation 比對、Step 3 的 GitRepository revision、Step 4 的
    `nslookup` 加正對照，這三個都能寫成腳本；Step 0 的 `age-keygen -y` 比對也能。
    **人執行的檢查清單會漂移，而它漂移的方式與被正確執行一模一樣**
  - 不是要取代 7.2，是要讓 7.3 的 factory agent 有東西可以跑
  - **`scripts/delivery-check.py`**（2026-08-17），五個子命令：`escrow`、`repo-hygiene`、
    `dns`、`flux`、`lan`
  - **三種結束碼而不是兩種**：0 通過、1 失敗、**2 判斷不出來**。第三種是這支腳本的重點——
    「量不到」與「量到了沒問題」在只有兩種結束碼時會被迫合併，而合併的方向永遠是綠的
  - 每個檢查都帶正對照或拒絕回報通過：`repo-hygiene` 的歷史查詢會另外確認同樣的查詢形狀
    找得到 `*.md`（否則空結果可能只是查詢壞了）；`lan` 一定連 `github.com` 一起查
    （否則一座對所有名字回 NXDOMAIN 的叢集看起來完全正常）；`dns` 沒有 token 時回 2 而不是 0，
    並明說沒驗到的正是「你的 token 看到的是不是同一個 zone」那一半
  - **雙向都測過，不是只測會通過的那條路**：
    - `repo-hygiene` 對本 repo 回 PASS，對 **jg-jiahd 回 FAIL** 並指出 `.gitignore` 未追蹤
      與 12 個 commit 有 `*cluster.yaml`——真實的缺陷，不是造出來的案例
    - `escrow` 四種輸入：正確副本 PASS；**截斷副本 FAIL**（它存在的理由）；有效但屬於別座
      叢集的金鑰 FAIL；檔案不存在 FAIL
    - `flux` 對 jg-jiahd 用當前 sha PASS、用錯的 sha FAIL
    - `dns` 對 `jiahd.cc` 兩個 DoH resolver 一致 PASS，對未委派網域 FAIL
  - `lan` 沒有實測——需要在客戶 LAN 上的一台 client 執行，這裡不具備條件
- [ ] 7.2 **[P2]** 由人工照 runbook 逐步執行一次完整 provisioning，修正指令與斷言的錯誤
  - **需要一次真實交付與一個人**，本 session 做不到。這是 7.0 與 7.1 的收斂條件而不是形式：
    7.1 初稿的 `cluster.yaml` 那條寫反了，是被別的 session 帶來的一個事實撞出來的，不是被
    審閱抓出來的。**一份沒被執行過的 runbook，其正確性沒有任何證據**
  - 跑的時候請記錄「哪一步的指令與現實不符」，那才是本項的產出；「跑完了」不是
- [ ] 7.3 **[P2]** 交由 factory agent 自動執行同一份 runbook，比對結果一致
  - 卡在 2.4（factory 還沒有 workload）與 2.1a（jcom 尚未選入）。**也卡在 7.2**：
    在人跑過之前，agent 跑出來的差異無法歸因是 agent 錯還是 runbook 錯
- [ ] 7.4 **[P2]** 在 `CLAUDE.md` 新增 factory agent 與交接流程章節，並移除已被 factory 取代的手動 port-forward 說明
  - ⚠️ **現在做會刪掉唯一還能用的程序。** factory 尚未部署（2.4 未過、2.1a 未做），
    所以手動 port-forward 不是「已被取代」，它是目前**唯一**能取得 Omni 存取的方式。
    本項的前置條件是 factory 真的在跑，不是 factory 被設計完
  - 另註：本項會動 `CLAUDE.md`（本 repo 的 agent 指示檔）。等 7.3 完成後由 ferry133 過目再改

## 8. 驗收  **[P2]**

- [ ] 8.1 以 scratch 工單完成一次全自動 provisioning，全程無人介入
- [ ] 8.2 在流程中途強制中斷 factory agent，驗證重啟後由工單續跑且無重複外部資源
- [ ] 8.3 模擬 QUIC 封鎖，驗證自動修復成功並留下記錄
- [ ] 8.4 模擬機器未上線，驗證回報列舉可能原因且不斷言
- [ ] 8.5 **[延後]** 第一台真實客戶以「agent 執行、人在旁看」模式交付，事後檢討工單留痕
- [ ] 8.6 回寫所有 spike 結論到 `design.md` 與相關 spec，確認無「待驗證」項目遺留

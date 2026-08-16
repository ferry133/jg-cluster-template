## Context

三個 repo 的分工已經穩定：`jg-base` 放 golden manifests、`jg-cluster-template` 放 schema 與工具鏈、每個 user repo 放 `cluster.yaml` 與 Flux 進入點。缺的不是設計，是**執行者**——目前每一台交付都靠人依 README 手動走完，而 README 本身混雜了 operator、進階使用者與上游殘留三種讀者的內容。

`deployment-profiles`（change ②）把 appliance 的客戶必填欄位降到 0，證明這些值可以由程式推導。本 change 補上跑這段流程的東西。

已查證的現況：

```
jcom cluster.yaml
  extras: [... omni/omni ...]        ← Omni 就跑在 jcom 裡
  cloudflare_domain: janncot.com
  claude_instances: ["cc"]

jg-base/kubernetes/apps/base/claudecode/claude-code/app/rbac.yaml
  單一 ServiceAccount → ClusterRoleBinding → cluster-admin
  「Shared by every claude-code instance」  ← factory 若沿用即無隔離

CLAUDE.md 已記錄但仍需人工執行的兩件事：
  - omnictl 需先 kubectl port-forward -n omni svc/omni 18080:8080
  - Cloudflare Tunnel 破壞 gRPC trailers，Omni 必須走直連 gRPC 路徑
```

物理上不可壓縮的客戶動作只有三件：開箱、插網路線、插電開機。前提是機器出廠時 Talos 已在碟上、ISO 已內嵌 SideroLink join token——之後機器自己回連 Omni，遠端就有完整能見度。

## Goals / Non-Goals

**Goals:**
- 一台 appliance 從機器上線到 `im` 可登入，全程無人介入。
- 流程冪等、可續跑，中斷不產生重複的外部資源。
- 部署狀態有稽核軌跡，人與 agent 讀同一份。
- 「客戶隨時能拿回鑰匙」成為可執行動作並經演練驗證。
- factory 的高權限憑證與其他 agent 隔離。

**Non-Goals:**
- 不做客戶面的 UI 與通知內容（change ④）。
- 不做 README 拆分（change ④）；本 change 只產出 operator runbook / skill。
- 不做 jcom 的高可用（依約定，量體成長後再處理）。
- 不做手機 App；out-of-band 能見度缺口在本 change 只被「誠實回報」，不被解決。
- 不涵蓋 `revive-talos-path`（change ①）。appliance 只走 Omni。

## Decisions

### D1. factory 跑在 jcom，且與 Omni 同叢集是主要理由

Omni 以 `omni/omni` extra 跑在 jcom 內，factory 放同一個叢集即可用 ClusterIP 直連 gRPC。這一步同時消掉兩個既有痛點：不必 `kubectl port-forward`，也不會踩到 Cloudflare Tunnel 破壞 gRPC trailers（`cluster.sample.yaml` 記錄的 2026-07-30 問題）。

**同叢集的代價已量測並被明示接受**（2026-08-16，`ferry133/jg-cluster-template#3`）：與 factory
同叢集的還有 `claudecode/claude-code`，而它綁 cluster-wide `cluster-admin`，所以任何通過該終端機
入口（預設 Auth0 OIDC）的人都讀得到 factory 的 Secret。ferry133 選擇 (a)——接受並記錄於 2.9，
以「日後可能為 IM 另開叢集」為預定方向。詳見下方 Risks 第一項；那裡也記著為什麼「只搬 IM」
還不夠。

**部署位置一併更正**：factory 放 `kubernetes/apps/extras/factory/factory/`，由 jcom 的
`cluster.yaml` 選入，與 `omni/omni` 同一機制。`apps/base/` 是**發佈範圍**而非目錄——它一小時內
到達每一座叢集且無逐叢集審核，會把這個憑證集中點送上客戶 appliance。

*Alternative considered*：跑在 jg-jiahd。捨棄——與 Omni 不同叢集，等於把剛消掉的兩個問題請回來。
*Alternative considered*：一次性 Job 而非常駐。捨棄——provisioning 是長時間、事件驅動、需要續跑的流程，常駐比較自然；且常駐實例也是 operator 平時的操作入口。

### D2. factory 不是 claude-code instance，是獨立 app

`claudecode/claude-code/app/rbac.yaml` 是單一 ServiceAccount 綁 cluster-admin、所有 instance 共用。若把 `factory` 加進 `claude_instances`，它與 `cc` 同 namespace、同 SA——`cc` 的任何一次 prompt injection 都能讀到 Omni Admin SA、GitHub PAT 與 Cloudflare 母帳號 token。

因此 factory 走獨立 namespace + 獨立 SA + 最小權限。現在改幾乎零成本（instance 還沒建），之後改要動 jg-base 的共用結構。

順帶一提：factory 對**客戶叢集**的 cluster-admin 來自它從 Omni 產生的 kubeconfig，不是來自 jcom 上的 RBAC。兩者是不同的授權面，不該混為一談。

### D3. 狀態機用 GitHub Issue，不另造 state store

repo 已有 `docs/agents/issue-tracker.md` 與 `docs/agents/triage-labels.md`。每台叢集一個 Issue 當工單：label 表階段、comment 記進度與外部資源識別碼。

好處是同時滿足四個需求：durable state、resume 輸入、稽核軌跡、人類可讀。不需要另一套資料庫，也不需要為 agent 另寫查詢介面。

限制要寫死：**comment 內不得出現任何金鑰材料**，只放識別碼與非敏感證據。

*Alternative considered*：repo 內的 state 檔。捨棄——會與 `task configure` 的產物混在同一個 commit 流，且沒有現成的 UI。

### D4. 冪等靠「決定性命名 + 先查後建」，不靠鎖

每個外部資源以工單可推導的決定性名稱建立（cluster 名、repo 名、tunnel 名皆由 `cluster_name` 決定）。每一步先查詢是否已存在，存在就採用。這樣中斷後重跑會收斂，不會產生第二條 tunnel 或第二個 repo。

當「記錄的狀態」與「觀察到的外部狀態」矛盾時**停下來升級**，不猜。自動化在資訊不足時繼續動作，比停下來危險。

### D5. 完成的定義是「`im` 可達」，不是「Flux 綠了」

Flux reconcile 成功不代表客戶拿得到東西。把完成點定在常駐 agent 可達，交棒才有明確界線：在那之前 factory 負責，之後由客戶叢集內的 agent 負責，factory 除非被明確重新召喚否則不再動它。

### D6. 已知失敗自動修，未知失敗停下來

cloudflared 因 ISP 封鎖 QUIC 而 CrashLoop 的 workaround 已記錄於 `CLAUDE.md`（`TUNNEL_TRANSPORT_PROTOCOL: http2`），這類有明確症狀與明確解法的，agent 應自行套用並記錄。

沒有既定解法的則停下、留下診斷證據、升級。**不無限重試**——重試在跨系統流程裡多半只是把失敗推遲並放大。

### D7. 「機器沒出現在 Omni」誠實回報，不假裝知道原因

所有遠端能見度都建立在 SideroLink 之上。機器沒回連時，agent 無法區分「沒插電 / 沒插網路線 / ISP 擋了出口 / 開錯磁碟」。規格明訂**列舉可能原因而不斷言其一**，並附上非技術人員可執行的現場檢查清單。

這是本設計已知的最大盲點，本 change 不解決它，只要求不要用猜測掩蓋它。手機端的 LAN 探測（change ④ 之後）才是解法。

### D8. 服務身分與登入身分分離

- **服務身分**：該叢集持有帳號用（Cloudflare 註冊信箱等）。
- **登入身分**：客戶自己的日常信箱，用來登入 `im`。

若兩者合一，稽核上分不清哪個動作是 operator 做的、哪個是客戶做的。

**自動建立消費者 Google 帳號不可行**：Google ToS 禁止自動化註冊、強制 SMS 驗證、同號碼可開帳號數有限，繞過會導致帳號連同其上的 Cloudflare 一起被停用——那是最糟的失敗模式（叢集鑰匙隨帳號蒸發）。可自動化的替代是自有網域下的 Workspace 使用者（Admin SDK Directory API），或 Cloudflare Email Routing 別名當註冊信箱。

### D9. 交接是一個動作，驗收是一場演練

`task handover` 一次處理六項：SOPS 金鑰換成客戶公鑰（`sops updatekeys`，不需把密文解到 repo 裡）、repo transfer、Cloudflare 帳號信箱、Omni 控制權、模型 API 憑證、k8s 存取。並產出交接封裝清單。

驗收標準刻意設成**演練**：由一個沒有 operator 任何權限的人，只拿封裝，完成「reconcile 一次變更、解密一個 secret、登入常駐 agent」。演練沒過，就不對客戶宣稱可以交接。

理由：交接是那種「以為做完了、真的要用時才發現少一把鑰匙」的事，只有實際走一遍才算數。

### D10. runbook 與 skill 是同一份檔案

`.claude/skills/provision-customer-cluster/SKILL.md` 寫成「前置條件 / 指令 / 驗證斷言 / 失敗分支」的形式。人可以照著做，agent 可以照著跑。這樣「SOP」與「agent 的程式」不會分岔——分岔的文件必然有一份是錯的。

### D11. ~~Cloudflare 由 operator 提供~~ → 客戶自有一個 Google 帳號，公司用它代為註冊

**2026-08-16 由 ferry133 決定改寫**（`ferry133/jg-cluster-template#5`）。原本的形狀是「Cloudflare
帳號在 operator 側、客戶零輸入」；新的形狀是**客戶申請一個代表這座叢集的 Google 帳號**，
Cloudflare、Auth0 與其餘外部服務都由公司**用那個帳號**註冊。客戶把密碼告訴公司、取得服務；
服務結束時客戶改掉密碼。

> 「Google 帳號是客戶自己申請，告知公司密碼，取得公司服務。公司服務結束，客戶就可以修改
> 他的密碼。」——ferry133，2026-08-16

這一步同時解掉 `proposal.md` 記的那個問題：「客戶隨時能拿回鑰匙」原本只是口頭承諾，因為
`age.key`、GitHub repo、Omni 控制權與 Cloudflare 帳號散在四個地方，沒有任何單一動作能把它們
交回去。這個模型把**外部服務**收斂到客戶本來就持有的一個憑證上。

連帶死掉兩個 spike：1.2（Workspace Admin SDK 的最小權限與 domain-wide delegation）整題消失，
因為帳號是客戶自己申請的，公司不建立任何使用者；1.3 的 Tenant API 資格問題同樣消失，
連我先前提的「子帳號 vs 委派存取」也一併消失——兩者皆非，那就是客戶自己的帳號。

**零 IT 的三個物理動作不受影響**：申請 Google 帳號發生在簽約時、出貨之前，不是客戶在門口要多
做的第四件事。明寫在這裡，免得日後有人來「修正」一個並不存在的衝突。

⚠️ **這個模型的中心主張尚未實測**：改密碼會擋住取得**新**憑證，但擋不掉**已簽發**的
——Cloudflare API token 與 Auth0 client secret 是獨立的 bearer 憑證，有效性不依賴帳號怎麼登入；
而 escrow 的 `age.key` 完全不受密碼變更影響，它照樣解得開每一份既有封存。**沒有人測過
Cloudflare API token 在密碼變更後是否存活**——jg-base-90、fleet-ops 與我都只是推論。
在真帳號上花幾分鐘就能定案，而它決定這個模型成不成立，所以它屬於 ferry133 的待辦而不是
設計文件裡的假設。撤銷清單見 6.4。

以下段落是**改寫前**的理由，保留因為它解釋了為什麼不能要求 appliance 客戶自製 scoped token
——那個限制在新模型下依然成立，只是解法從「operator 提供帳號」換成「公司用客戶帳號註冊」：

先前討論中曾提到「請客戶給一個 scoped token 而不是帳號密碼」——那對 prosumer / full 成立，對 appliance 不成立：建一個 scoped token 需要有 Cloudflare 帳號、登入、找到 API Tokens、看懂 `Zone - DNS - Edit` 與 `Account - Cloudflare Tunnel - Read` 該怎麼勾、再安全地把 token 交出來。第三步以後全是 IT 工作，零 IT 客戶做不到。

先前討論中曾提到「請客戶給一個 scoped token 而不是帳號密碼」——那對 prosumer / full 成立，對 appliance 不成立：建一個 scoped token 需要有 Cloudflare 帳號、登入、找到 API Tokens、看懂 `Zone - DNS - Edit` 與 `Account - Cloudflare Tunnel - Read` 該怎麼勾、再安全地把 token 交出來。第三步以後全是 IT 工作，零 IT 客戶做不到。

`deployment-profiles` 的 spec 其實已經把 `cloudflare_domain` 與 `cloudflare_token` 列為 **operator-supplied**——「客戶必填 0 項」不等於「欄位 0 個」，是那些欄位由 operator 填。zone 住在 operator 的 Cloudflare 帳號裡，token 也是 operator 的，客戶從頭到尾不碰 Cloudflare。

**網域歸屬選定：客戶自己的網域，NS 委派到 operator 的 Cloudflare 帳號。**

| | 客戶要做什麼 | 交接時 | |
|---|---|---|---|
| A operator 的子網域 `im.<cluster>.jgcloud.xx` | 無 | 客戶得自備網域，**所有 URL 改變** | 捨棄 |
| **B 客戶自己的網域** `im.customer.com` | 買一個網域（消費行為，非設定行為） | NS 指回去，**URL 不變** | **選定** |
| C Cloudflare Tenant API 子帳號 | 無 | 子帳號整個轉移 | 需 partner 合約，列為後續選項 |

選 B 的理由與 `deployment-profiles` 拒絕 `.lan.` 命名前綴完全相同：**hostname 一旦改變，成本落在使用者身上**——書籤、IoT 與 MQTT client 的位址、HomeKit 配對、Auth0 的 Allowed Callback URLs、憑證 SAN 全都要重配。A 讓交接必然引發一次全面遷移；B 讓 hostname 從第一天就是最終形態，交接只是把 NS 指回去，客戶那端什麼都不用改。

「買一個網域」對零 IT 客戶是可行的——那是消費行為，不是設定行為。要更省事，**operator 可代購並以客戶名義註冊**，那樣連這一步也消失，且客戶在交接時拿到的是一個真正屬於他的資產。

### D12. onboarding 與 handover 的能力不對稱，是設計的一部分

```
onboarding   零 IT      客戶只做三個物理動作
handover     需要 IT    客戶要接手 Cloudflare zone、GitHub repo、Omni 控制權、age.key
```

這個落差是合理的——交接發生在服務關係結束時，客戶那時本來就該找人接手——但它**不該被客戶在交接當天才發現**。目前 `cluster-handover` 的 spec 只要求「交出去」與「演練通過」，沒有要求說明客戶需要什麼能力才用得起這些東西。

因此交接封裝除了列出持有什麼，還必須說明**要用它需要什麼能力**：需要有人能操作 Cloudflare DNS、能用 git 與 SOPS、能存取 Omni 或改用 Talos client cert。寫清楚讓客戶能判斷該自己接手還是外包，而不是拿到一包鑰匙卻打不開門。

## Risks / Trade-offs

- **factory 是權限集中點**（Omni Admin + GitHub PAT + Cloudflare 母帳號） → 獨立 namespace/SA、憑證不進 image、憑證清單與 blast radius 明文記錄。
  - **獨立 namespace/SA 限制的是 factory 做得到什麼，不是誰讀得到 factory**（2026-08-16 量測，
    `ferry133/jg-cluster-template#3`）。同叢集的 `claudecode/claude-code` SA 綁的是
    cluster-wide `cluster-admin`（jg-base `.../claude-code/app/rbac.yaml` 的 ClusterRoleBinding
    `claudecode-claude-code`），而 RBAC 純加法、沒有 deny，所以它讀得到任何 namespace 的
    Secret，包含 factory 的。**原文寫的隔離不成立**——不是實作沒做到，是那個手段做不到那件事
  - **ferry133 於 2026-08-16 選擇 (a)：接受這個暴露，並寫進 2.9 的憑證清單。**
    因此 **2.9 不再是「記錄殘餘風險」，它就是全部的緩解措施**——清單漏掉的東西不是「已接受的
    風險」，是「沒被記錄的風險」，而這兩者從外面看完全一樣
  - **(d) 是預定方向，不是被否決的選項**：日後可能為 IM 另開叢集。所以現況是**選定的中繼點
    而不是結論**，六個月後讀到這段的人需要知道這件事
  - ⚠️ **但「把 IM 搬去自己的叢集」本身關不掉這條路**：`cc` 與 `im` 共用同一個 `claude-code`
    SA，所以少了 `im` 的 jcom 上還有 `cc`，一樣是 cluster-admin。真正關得掉的是 (d) 的完整
    形式——在 factory 叢集上不選 `claudecode`，而那要先把它移出 jg-base 的 `apps/base/`
  - ~~**「可輪替」對其中一類憑證是假的**：若 factory 承擔 5.5 的 escrow，它同時持有 N 把
    客戶 `age.key`，而那把鑰匙輪替不了——集中一個沒有撤銷路徑的憑證，與集中一個有撤銷路徑的，
    是不同的風險類別而不是同一類的更多量~~
  - **上述前提已於 2026-08-17 被決策移除**：ferry133 定為「factory doesn't do escrow.
    employee action.」（`ferry133/jg-cluster-template#6`）。factory 持有的三把——Omni SA、
    GitHub PAT、Cloudflare——**每一把在起疑時都撤銷得掉、重發得出來**
  - **因此 (a) 今天比它被選擇的當下更站得住腳**，這一點要寫下來而不是讓舊的疑慮留在紀錄裡
    繼續生效：選 (a) 時最重的那一項——沒有撤銷路徑的客戶金鑰——已經不在 factory 的爆炸半徑內。
    2.9 的清單仍要列出那三把（用途、範圍、blast radius、輪替方式），但**不必再列 `age.key`
    「已接受」**，因為它不再在裡面
  - 代價轉移到別處而不是消失：escrow 改由人手執行，唯一分辨真做與宣稱的東西是 §7.0 那筆
    記錄的措辭
- **jcom 是所有客戶的管理面單點** → 已接受。jcom 失效時客戶叢集本身照常運行，失去的是遠端管理能力。量體成長後再處理高可用。
- **「機器沒出現」時 agent 全盲** → 本 change 不解決，只要求誠實回報 + 現場檢查清單。缺口留給後續的客戶端探測。
- **自動修復可能修錯東西** → 只對有明確症狀比對的已知失敗自動處理，其餘一律停下；每次修復都留下症狀、動作與驗證結果。
- **GitHub Issue 當狀態機依賴 GitHub 可用性** → GitHub 不可用時 provisioning 本來就無法進行（repo 也建不了），不構成額外相依。
- **交接後 operator 無殘留存取，等於失去救援能力** → 交接封裝需明載「若保留支援關係，operator 保留哪些存取」，讓它是明示選擇而非預設。
- **Workspace 服務身分綁在自有網域** → 客戶無法真正「擁有」該身分。因此交接時的正解是把帳號註冊信箱改成客戶自己的，而不是把 Workspace 使用者交出去。

## Migration Plan

1. 先建 factory 的 namespace / SA / RBAC 與憑證，但不接任何真實客戶——用 scratch 工單跑通流程。
2. runbook/skill 先以**人工執行**驗證每一步的指令與驗證斷言正確，再交給 agent 自動跑。
3. `task handover` 先在 scratch 叢集完成演練，通過後才納入對外承諾。
4. 第一台真實客戶採「agent 執行、人在旁看」模式，工單全程留痕，事後檢討再放手。
5. **Rollback**：factory 是新增元件，停用它不影響任何既有叢集；手動流程（現行 README）仍然可用，作為逃生梯。

## Open Questions

- Omni 是否提供「新機器註冊」的事件訂閱，還是只能輪詢？輪詢間隔與 API 成本影響「機器上線到開始 provisioning」的延遲。
- Google Workspace Admin SDK 建立使用者所需的最小權限範圍為何？是否需要 domain-wide delegation（那會擴大 blast radius）。
- 「每客戶一個 Cloudflare 帳號」若不走 Tenant API（需 partner 合約），可行的替代是什麼？沿用單一母帳號 + 每叢集 scoped token 是否足以支撐交接？
- Omni cluster 的控制權能否轉移給客戶自有的 Omni 實例？若不能，交接時是否改發 Talos client cert kubeconfig（jcom 已是此模式）？
- factory 對客戶叢集的存取憑證存活期多長？長期持有等於長期風險，但每次重新取得又需要 Omni Admin——這個取捨還沒定。

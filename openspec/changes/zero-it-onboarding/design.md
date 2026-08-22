## Context

②讓 appliance 的客戶必填欄位降到 0，③讓部署流程無人介入。這兩者加起來讓「客戶什麼都不用做」在技術上成立，但客戶那一端仍然空白——他收到一個箱子，沒有任何東西告訴他要做什麼。

現行 `README.md` 無法擔任這個角色，而且已與 repo 脫節（已查證）：

```
README.md:102   gh repo create --template onedr0p/cluster-template   ← 指向上游
README.md:205   just bootstrap talos                                 ← 無 justfile
README.md:20    「6 stages」                                          ← 實際寫到 Stage 7
README.md:243   cp kubeconfig-sa kubeconfig                          ← CLAUDE.md 明文禁止
```

一份自己都不正確的文件，不可能拿去給不懂 IT 的人照著做。

另一個已查證的結構限制：`jg-base/kubernetes/apps/extras/default/linebot/` 有完整的 LINE webhook gateway（`app/deploy.yaml:28` 的 `line_gateway.py`）與 knowledge PVC，但它是**部署在客戶叢集的 extra**。onboarding 發生在客戶叢集存在之前，所以不能用它——這是與 ③ 相同的雞生蛋問題，解法也相同：跑在 factory 側。

## Goals / Non-Goals

**Goals:**
- 客戶只做三件事：開箱、插網路線、插電開機。
- 客戶全程知道發生什麼、要多久、成功了沒有、出錯找誰。
- 文件依讀者拆分，且每一份都正確。
- 解除 ② task 1.4 的阻塞（rebinding protection 偵測需要客戶端視角）。

**Non-Goals:**
- 不做原生 App。本 change 只定義它未來要接上的介面。
- 不做 operator runbook（③ 的 skill 已承擔），本文件只連結。
- 不移除手動 Talos 路徑（①），它保留在進階使用者文件裡。
- 不設計計費、合約、退貨流程。

## Decisions

### D1. 文件依讀者拆，不依主題拆

```
README.md                 這是什麼 + 把讀者導向正確的文件（不含步驟）
README-zero-IT.md         客戶：三個動作、會發生什麼、出事找誰
docs/deploy/manual.md     進階使用者：完整手動路徑，含 (A) Talos
.claude/skills/…/SKILL.md operator：可執行 runbook（③ 建立，此處只連結）
```

依主題拆（網路一份、儲存一份）會讓每個讀者都得跨檔案拼湊。依讀者拆，每個人讀完一份就夠。

規格層面加了一條容易被忽略的約束：**operator runbook 只連結不重複**。文件一旦分岔，必然有一份是錯的，而錯的那份會被照著執行。

### D2. 零 IT 文件的成功標準是「未受訓讀者無協助完成」

不是「寫得夠簡單」這種主觀判斷，而是實測：找一個不懂 IT、事前沒被告知流程的人，只給箱子和紙本說明。任何一次猶豫、發問、做錯，都算文件缺陷，改完再測。

這與 ③ 的交接演練是同一種驗收模式：**不能宣稱、只能演示**。

### D3. 紙本隨箱出貨，QR code 只是輔助

客戶讀這份文件的時候，網路還沒通。任何以 URL 為唯一入口的設計在那一刻都是失效的。所以紙本是主，QR code 是輔。

連帶要求：紙本與 `README-zero-IT.md` **同源產生**，否則兩者會分岔，而分岔的那一份正好是客戶手上那份。

### D4. 「三個物理動作」是規格，不是願望

規格明訂客戶文件裡不得出現燒錄媒體、改 BIOS 開機順序、設定路由器、輸入位址、建立帳號。這些不是「盡量避免」，是**必須在出貨前消除**——出廠時 Talos 已在內碟、ISO 已內嵌 SideroLink join token，客戶插電就會自己回連。

把它寫成規格的用意是：任何一次「這個就讓客戶自己弄一下吧」的妥協，都會在驗收時被 D2 的實測擋下來。

### D5. LINE bot 跑在 factory 側，不在客戶叢集

`default/linebot` 是客戶叢集的 extra，onboarding 當下那個叢集還不存在。所以 onboarding bot 是 factory 側的獨立部署，沿用 linebot 的 webhook gateway 形態與既有的 LINE 憑證欄位（`line_channel_access_token` / `line_channel_secret` / `line_notify_group_id` 已在 CUE schema 裡），但不共用實例。

附帶好處：客戶叢集掛掉時，溝通管道仍在——那正是最需要它的時候。

### D6. 先 LINE bot，原生 App 延後

手機的價值有八成不需要 App：

| 能力 | LINE | 需要原生 App |
|---|---|---|
| 推播進度 | ✓ | |
| 三題 intake | ✓ | |
| 客戶拍照回傳 | ✓ | |
| 對話式排錯與升級 | ✓ | |
| **掃 LAN / 測 UDP 出口** | ✗ | ✓ |

而 LINE 的 plumbing 已經存在、客戶已經裝了、沒有 app store 審核與更新問題。所以 v0 用 LINE 涵蓋四項，v1 才為了最後一項做 App。

本 change 只做 v0，但**先把 v1 的介面定死**：probe 的結果必須經由與客戶觀察相同的證據路徑寫進工單，這樣加上 App 不需要改工單模型、不需要改流程、也不改變客戶做的三件事。

### D7. 平台限制要先查清楚再決定 App 範圍

iOS 沒有 raw socket，做不了 ARP 掃描；mDNS 需要 `com.apple.developer.networking.multicast` entitlement 且要個案核准。實際能做的大概是 TCP connect 掃 /24 的特定 port——這剛好就是現行 README 用 `nmap -p 50000` 在做的事，很可能夠用。

規格寫成「**先確立限制，再決定範圍**」，避免把 App 設計在一個上架不了的能力上。答不出來的問題就留給人工升級，不硬塞進 App。

### D8. 診斷問題先列舉，再分配機制

不先列問題就做工具，會做出一個回答不了關鍵問題的工具。所以先把「只有站在客戶網路裡才答得出來」的問題列全，每一題標明由觀察、拍照、還是自動探測回答。

目前的分配：

```
機器有沒有通電        → 觀察（燈號）
網路線有沒有插好      → 觀察
開機碟對不對          → 拍照
LAN 上位址是否被佔用  → 探測（延後）
ISP 是否擋出站流量    → 探測（延後）
DNS rebinding 過濾    → 探測（延後）← ② task 1.4 卡在這
```

延後的三題目前只能人工升級，規格要求**明確標為延後**而不是靜默無解。

### D9. 客戶失敗時得到的是「下一步動作」，不是「錯誤描述」

不懂 IT 的人拿到錯誤訊息無法轉換成行動。規格明訂：任何失敗都要給出非技術語言的具體下一步，且永遠有一條「找人」的路。

現場檢查一律用可觀察的語言表達（「燈是什麼顏色」、「線有沒有插到底」），不要求客戶判斷任何抽象狀態。

### D10. 1.4 的收款人已經不在了，而被動觀察在 appliance 上量不到

> **2026-08-21 追記：收款人現在一個都不剩了。** 下面說「還在等這個機制的是
> `deployment-profiles` D45」——D45 已由 **D48** 取代，而 D48 改問「答案有沒有到」，
> 在節點的一般解析路徑上就量得到，不需要任何客戶端視角。1.4 剩下的用途只有本檔
> 那張分配表上延後的三題。

1.4 原本寫「若可行，回報 `deployment-profiles` task 1.4 解除阻塞」。**那個任務已經是
`[x]`**：它在 2026 年就裁定由節點自行查詢路由器，並實作進 daily-check；隨後 1.3 發現
擋住 RFC1918 的不是客戶路由器而是 Cloudflare 自己（D29），偵測因此失去用途、保留但
安靜跳過。**1.4 說要解開的東西沒有被鎖著。**

還在等這個機制的是 `deployment-profiles` D45 的第三個方向——每台 appliance 出廠即帶著
一個永遠紅、且扣住 dead-man switch 的健檢，而三個修法裡「由客戶端回報」需要這裡先有
機制。所以 1.4 該做，但收款人要改寫。

**先測了一個 D45 沒列的第四個方向：不問任何人，看誰在問我們。**
`k8s-gateway` 的 Corefile 開著 `log` 與 `prometheus 0.0.0.0:9153`（兩座叢集皆確認），
查詢紀錄逐筆帶來源 IP。路由器若不再把 DNS 指向叢集，LAN 上就沒有人會來問——沉默本身
就是訊號，而且不需要客戶做任何事。

2026-08-20 實測兩座叢集：

| | 來源 | 24h | 6h | 1h | 7d |
|---|---|---|---|---|---|
| jg-jiahd（3 節點，條件轉發生效中） | 全部來自 `10.9.9.1`（路由器） | 629 | 54 | **1** | — |
| jgt-appliance（出貨形狀，`lan_shared_addr` 已釘 `10.9.1.254`） | `10.9.1.1` ×1、`127.0.0.1` ×2 | 1 | — | 0 | **3** |

**結論：這個方向在 appliance 上不成立。** 一週 3 筆（其中 2 筆還是本機）意味著「今天零查詢」
是常態，沉默因此不能當作故障。jg-jiahd 的 629/日 看起來夠用，但那是三節點住家 + 條件轉發，
不是出貨形狀；而且同一座叢集在某個小時內只有 1 筆，任何小於一天的窗口都會誤報。

**附帶產出兩件事**（都不是原本要找的）：

1. **來源 IP 可以反推路由器用的是哪一種做法**，不必叢集「被告知」：全部來自路由器位址
   ＝條件轉發；來自大量 LAN 位址＝DHCP 發叢集位址。D45 對第二個方向的反對是「要求叢集
   知道一件它管不到、而且會漂移的事實」——那件事實其實看得到，而且會跟著漂移。惟在
   appliance 的查詢量下同樣推不動。
2. jgt-appliance 的 k8s-gateway 七天內留下 **337 行** `[WARNING] plugin/health: Local
   health request to "http://:8080/health" took more than 1s`。與 1.4 無關，另記。

### D11. 瀏覽器版偵測要有一個共享待測性質的正對照

> **2026-08-21：這個設計目前沒有收款人**（D10 追記）。它仍然正確——若哪天要做客戶端
> 回報，正對照與 HTTP 的要求都成立——但沒有東西在等它，而下面那條 jg-base 的阻礙
> 也就不必先解。

若仍要走客戶端回報，v0（無 App）可行，但**不能只問「內網名稱打得開嗎」**：打不開有
DNS 被過濾、服務沒起來、位址錯了、客戶端隔離四種解釋，瀏覽器的 fetch 失敗對四者一視同仁。

要能鑑別，正對照必須指向**同一台伺服器、同一個埠、同一個路徑**，只差在有沒有經過 DNS：

1. 客戶用手機開 `http://<lan_shared_addr>/…`（字面 IP，完全不經 DNS）。
   **頁面載入本身就是正對照**——證明這支手機在這個 LAN 上構得到叢集。
2. 頁面再向 `http://internal.<domain>/…`（同一台伺服器）發一次請求。
3. 一成一敗，差異只可能是 DNS。兩個都成＝內網名稱在客戶端可用；兩個都敗＝手機根本沒
   在這個 LAN 上，該問的是別的問題。

必須是 HTTP 而非 HTTPS：頁面若由通道以 HTTPS 送出，混合內容會擋掉對 `http://` 的請求，
而 `https://<ip>` 沒有合法憑證——正對照會消失在一個與失敗無法分辨的錯誤裡。

**而在出貨形狀上，那個「必須是 HTTP」目前不成立**（2026-08-20 讀 jg-base 原始碼確認）：
`envoy-internal` 的 port 80 listener
（`jg-base/kubernetes/apps/base/network/envoy-gateway/app/envoy.yaml:147`）被同檔 `:218`
的 `https-redirect` HTTPRoute 全面接管，任何 HTTP 請求 301 到 HTTPS。於是
`http://<lan_shared_addr>/` → 301 → `https://<lan_shared_addr>/` → 憑證簽給 `*.<domain>`、
對字面 IP 無效 → **正對照停在憑證警告上**——正是上一段要避開的那件事，只是來源不同：
D11 原本只想到頁面自己的混合內容，沒想到 gateway 會先把 HTTP 收掉。

同一個 listener 還有 `allowedRoutes: namespaces: from: Same`，所以 probe 頁面不放在
`network` namespace 就連掛都掛不上去。

兩條修法都落在 **jg-base**，不在本 repo：在 `network` namespace 加一條路徑比 catch-all
更長的 HTTPRoute（`/probe` 之類）搶在重導向前面，或給 probe 開一個獨立的 port。
**在那之前 D11 是不可部署的設計**——這是先決條件，不是實作細節。

**打字問題有解**：`lan_shared_addr` 在 `task configure` 時就已知（jgt-appliance 已釘
`10.9.1.254`），所以 factory 可以在出貨卡片上印該叢集專屬的 QR——即 4.7。不必等 §6 的 bot。

**但它修不了 D45。** dead-man 檢查每天要跑，而這個機制需要一個人拿手機做一件事。
一次性的安裝驗收它做得到；每日的外部契約監看它做不到。**D45 的第三個方向對它自己的
用途是無效的**，這件事要回寫 D45，不要留在那裡當作還有三個選項。

### D12. 出貨流程：raw 映像直接寫進內碟，而形狀由一個 preset 宣告（2026-08-21）

> **⚠️ 出貨手段已由 D14 取代（2026-08-22，實機驗證）。** 下面對 preset、tunnel、
> `--initial-labels`、join token 的判斷全部仍然成立——那些綁在 preset 上，與用哪種媒體
> 無關。**只有「怎麼把系統放進碟」這一段被換掉了**：不必寫 raw，讓 Omni 自己裝更省事，
> 而且不需要拆機或另做 live USB。

實測自 jcom 上的 Omni（唯讀查詢，port-forward 已關閉）。

**`omnictl media download <preset> --format raw`** 產出 `.raw.xz` 裸碟映像（另有 `iso`、
`qcow2`、`pxe`）。**所以不必走 ISO。** ISO 路線要求客戶端存在可開機媒體並選擇開機裝置，
而規格明訂那必須在出貨前消除（D6 段）。raw 寫進內碟之後，機器只有一個可開機裝置，
客戶不需要進韌體。

**preset 是出貨形狀的唯一宣告點。** `omnictl media preset create` 綁定：

| 旗標 | 為什麼對 appliance 要緊 |
|---|---|
| `--extensions` | **寫碟之前就要定案**。`docs/deploy/combinations.md` §5.4：事後換 schematic 要逐台重開機。現有 `omni-longhorn` preset 已帶 `siderolabs/iscsi-tools` + `siderolabs/util-linux-tools` |
| `--join-token` | 見下，這一格是 5.2 |
| `--initial-labels` | **工單綁定的決定性手段**（見下） |
| `--bootloader` | `auto` / `uefi` / `bios` / `dual`。現有 preset 皆 `auto` |
| `--use-siderolink-grpc-tunnel` | 見下，這一格決定機器回不回得來 |
| `--secureboot` / `--talos-version` / `--extra-kernel-args` | — |

#### `--initial-labels` 讓工單比對是決定性的

`factory-agent` 4.1／4.2 要求「未匹配任何工單的機器不得自動建叢集，改為回報 operator」。
**在寫碟時就把工單識別碼壓成機器標籤**，比對就成了查表，不是啟發式。現有的
`omni-longhorn` preset 已經帶著 `client 1` 這個標籤，形式是現成的。

這一項要回寫 `factory-agent` §4——它目前從「機器註冊偵測」起跳，而標籤是在更早一步
決定的。

#### ⚠️ SideroLink 預設走 UDP，而失敗看起來像機器沒開機

`--use-siderolink-grpc-tunnel` 的說明明寫：**只在網路封鎖 UDP 時才啟用**，因為 HTTP/2
隧道有顯著額外負擔。但 appliance 的出貨對象是**未知的客戶網路**。UDP 被擋時機器永遠
不回連，而從 factory 看過去，那與「客戶還沒插電」「機器開不起來」**產生一模一樣的觀察**
——正是 4.13 要回報的那一類，也正是 CLAUDE.md 那條「什麼都沒有至少有兩種解釋」。

本 repo 的 `CLAUDE.md` 已經記著一座叢集的出口封鎖 UDP 7844（cloudflared QUIC）。而
Omni 這邊，現有五個 preset 裡有兩個（`omni-longhorn`、`amd64-1.13.2-HTTP2`）已經開了
tunnel——**這個問題撞過**。

**裁定：appliance 出貨一律開 tunnel。** 用一份已知的頻寬代價，換掉一個遠端分辨不出來的
失效。要關掉它必須先有證據說明那台的網路不封鎖 UDP，而出貨時我們沒有那個證據。

#### join token 不能用預設那一顆（這是 5.2 的核心）

預設 token **永不過期、使用次數無上限**，而它會被燒進每一張出貨的碟。撿到一台機器的
映像，就能把任意機器註冊進整個 fleet 的 Omni。

`omnictl jointoken create --ttl <duration>` 可以開短期 token。**每批出貨一顆，TTL 覆蓋
運送與安裝窗口即可**，過期後那張碟的映像就註冊不了東西。

> ⚠️ 本次查詢在終端機列出過現有 join token 的 ID，而 join token ID **就是憑證本身**
> （它進到 kernel args 裡）。那份輸出應視為已洩漏，建議一併輪替。

#### 未驗，都需要實體機器

- raw 映像在目標硬體上是否**不改韌體就開得起來**（UEFI fallback path `\EFI\BOOT\BOOTX64.EFI`）
- **寫碟的實體手段**：USB-to-NVMe dock 直寫，或開機到 live 環境再寫——取決於機殼拆不拆得開
- `--bootloader dual` 是否必要（現有 preset 都是 `auto`，但它們不是出貨機）

### D13. join token 證明的是來歷，所以它不該過期（2026-08-21，2026-08-22 改寫）

> **標題原本寫「因為 D12 選了 raw 預裝」。** 前提在 D14 換掉了——出貨用的是「建拋棄式
> 叢集再刪掉」，不是寫 raw。**但論證本身沒有變**：關鍵從來不是用哪種媒體，而是
> **機器第一次回連之後，系統有沒有進到碟裡**。下面的推論原樣成立，且已於 2026-08-22
> 在實機上驗到 `PERSISTENT`（見 D14）。

5.2 真正要回答的不是「怎麼把 token 嵌進映像」——D12 已經答了（綁在 preset 上，任何格式
下載都帶著它）——而是**短 TTL 會不會弄壞已經加入的機器**。這件事不能推，會決定整個流程。

#### 答案在一個 OR 裡

`internal/pkg/siderolink/provision.go`：

```go
func (pc *provisionContext) isAuthorizedSecureFlow() bool {
	return pc.hasValidJoinToken || pc.hasValidNodeUniqueToken
}
```

**持有有效 node unique token 的機器，即使 join token 已過期或被撤銷，仍然通過授權。**
join token 只在「還沒有自己的身分」時才是必要條件。

#### 但那個身分只有裝了 Talos 才是持久的

`join_token_status.go` 對每台使用該 token 的機器產生警告，其中一條逐字是：

> `Talos is not installed so the generated node unique token is ephemeral`

所以：

| 供裝方式 | node unique token | join token 過期後 |
|---|---|---|
| **raw 預裝內碟（D12）** | 首次開機即 **PERSISTENT** | 機器不受影響 |
| ISO／維護模式 | **EPHEMERAL** | 機器仍依賴 join token |

**D12 的選擇不只是省掉客戶的動作，它同時是短 TTL 成立的前提。** 兩個決定是同一件事的
兩面——若哪天有人為了方便改回 ISO 路線，這裡的 TTL 假設會跟著失效，而失效的樣子是
「某天機器就是連不回來了」。

#### 兩件會讓這個論證失效的事

1. **Talos 版本太舊** → 警告變成 `Installed Talos version does not support unique node
   tokens`，授權退回 `isAuthorizedLegacyJoin()`，那條路徑**只認 join token**。所以 preset
   的 `--talos-version` 要釘在支援 unique token 的版本，並在機器上線後確認該 token 的
   warnings 不含 `EPHEMERAL` / `UNSUPPORTED`。
2. **Omni 跑在 `legacy` join token 模式** → `nodeUniqueTokensEnabled` 為 false，整套機制
   關閉。原始碼預設是 `legacyAllowed`（≠ legacy，所以預設是開的），但 **jcom 上的實際
   設定我沒有驗到**——`omni` deployment 的 args 沒有相關旗標，設定應該在設定檔裡。

#### ~~TTL 選錯不是不可逆的~~ → **短 TTL 整個作廢**（ferry133，2026-08-22）

上面那整段（每批一顆短 TTL token、TTL 涵蓋運送窗口）是錯的。**推翻它的是「這顆 token
到底在做什麼」這個問題。**

它在做的是**證明來歷**：這台機器是從 janncot 的 Omni 出去的，所以它有資格回來，日後
擴充成客戶叢集的節點。而一個要證明來歷的憑證：

- **必須活得比機器久。** 五年後那台要證明自己是你出的，而憑證兩年前就死了
- **過期不是安全機制，是自我否定**——它專門讓「真的是你出的機器」失去證明能力

反方向也不構成威脅：陌生人把自己的機器註冊過來，得到的是「他送你一台機器」。它躺在
available 池裡，不會自己變成任何叢集的節點。

而我們量到的東西讓這顆 token 的角色更小：node unique token 是 **PERSISTENT**，
**連叢集被刪（會 reset STATE）都活下來**（D14）。所以五年裡的斷電、搬家、換網段、
重開機，join token 完全不參與。它只在兩個時刻有用：**第一次註冊**（D14 之後發生在工廠），
與**整碟抹掉後重新供裝**。

短 TTL 的代價正好落在後者：三年後要重做一台舊機器，得先發現 token 過期、開新的、
重燒媒體——而當下值班的人不會知道當年為什麼設 24 小時。

#### 要修的是範圍，不是壽命

預設 token 的真缺陷是**整個 fleet 共用一顆**：任一台機器的 kernel args 外洩就等於註冊
入口外洩，而且**沒辦法只撤銷受影響的那一批**。

| | 預設做法 | 本 change 原提案 | **定案** |
|---|---|---|---|
| 壽命 | 永不過期 | 24h | **不設** |
| 範圍 | 全 fleet 一顆 | 每批一顆 | 每客戶／每批一顆 |
| 為什麼要分 | — | 為了讓它過期 | **為了能單獨 `revoke`** |
| 外洩時 | 只能全撤 | 等它自己死 | `revoke` 那一顆（可逆，有 `unrevoke`） |

**`revoke` 才是安全反應的手段。** 用過期當安全機制，等於拿一個保證會在錯誤時機生效的
計時器，去換一個你本來就能隨時執行的動作。

#### ⚠️ 這個結論掛在一個前提上

**「沒有任何東西會自動把新機器指派進叢集。」** 目前由 `factory-agent` 4.2 保證（未匹配
工單的機器不得自動建叢集，改為回報 operator），加上 D12 的 `--initial-labels` 讓陌生機器
配不到任何工單。

**哪天有人為了自動化方便，把「偵測到新機器就開始供裝」加進 §4，這個假設會無聲失效**——
而改的人不會知道自己動到的是一道安全前提。這條依賴要跟著 4.2 一起讀。

殘留成本不是零但很小：陌生機器佔一個 SideroLink peer、送 kernel log 進 Omni 的 log sink。
量大時是資源問題，不是權限問題。

#### 出貨流程（5.2 定案）

1. `omnictl jointoken create --ttl <涵蓋運送＋安裝窗口>` —— **每批一顆，不用預設那顆**
   （預設 token 永不過期、使用次數無上限，而它會燒進每一張出貨的碟）
2. `omnictl media preset create --join-token <id> --extensions … --initial-labels …
   --use-siderolink-grpc-tunnel --talos-version <支援 unique token>`
3. `omnictl media download <preset> --format raw` → 寫入內碟
4. 機器上線後確認：出現在 Omni、且該 token 的 warnings **不含** `EPHEMERAL` 或 `UNSUPPORTED`
5. 整批註冊完成後 `omnictl jointoken revoke <id>`。**用 revoke 不用 delete**——revoke 有
   `unrevoke` 可回復，delete 沒有

#### 讀的是哪一份原始碼

`~/coding/omni` @ `76af8b22`（2026-05-29）。**部署在 jcom 的 Omni 比它新**——證據是
部署版的 `omnictl` 子指令叫 `media`，而這份原始碼裡叫 `installationmedia`。以上是讀碼
所得，**沒有在活的機器上觀察過**：沒有實體機器，也不該為了驗證去撤銷一顆正在用的 token。

### D14. 出貨狀態由「建一個拋棄式叢集再刪掉」產生（2026-08-22，實機驗證）

要出貨的狀態有六項，缺一不可：

```
內碟有 omni-talos ／ 箱內無 USB ／ 從內碟開機 ／ 維護模式
／ 插電自行註冊回 office Omni ／ 不再依賴 join token
```

D12 用 `--format raw` 寫碟達成它。**可行，但要拆機或另做一支 Linux live USB。**
ferry133 提出用 Omni 自己的安裝流程,2026-08-22 在實機上跑完並驗證。

#### 程序

1. Omni ISO 開機（工廠用，不出貨）→ 機器以維護模式註冊
2. **建一個拋棄式叢集**，範本裡以 per-machine patch **明確指定安裝碟**
3. Omni 把 Talos 裝進該碟並重開機
4. **刪掉叢集** → 機器 reset，**碟上的系統保留**，回到維護模式
5. 拔 USB → 從內碟開機 → 自行註冊 → 出貨

#### 量到的（`e755a600`，Kingchuxing 256GB）

| 階段 | installed | maintenance | systemdisk | node unique token |
|---|---|---|---|---|
| ISO 開機、未安裝 | False | True | — | — |
| Omni 裝完 | **True** | False | `/dev/nvme0n1` | — |
| 刪掉叢集後 | **True** | **True** | `/dev/nvme0n1` | **PERSISTENT** |
| 拔掉 USB 後 | **True** | **True** | `/dev/nvme0n1`（USB 已從清單消失） | **PERSISTENT** |

**最後一列就是出貨狀態**，六項全部成立。D13 的核心斷言（裝進碟 → token PERSISTENT →
不再依賴 join token）**在實機上驗證了**，不再只是讀碼所得。

#### ⚠️ 安裝碟必須明確指定

那台機器當時插著 USB，Omni 回報兩顆：

```
/dev/nvme0n1   256 GB   nvme   Kingchuxing 256GB
/dev/sda        31 GB   usb    USB DISK 3.0        ← 就是那支開機碟
```

**讓 Omni 自動挑會裝進隨身碟**，而且過程看起來完全成功——拔掉才發現。範本裡的
per-machine patch 是這條程序唯一不能省的一行：

```yaml
kind: Machine
name: <machine-uuid>
patches:
  - idOverride: 100-<cluster>-install-disk
    inline: |
      machine:
        install:
          disk: /dev/nvme0n1
```

#### 兩件被實測推翻的事

**一、`talosctl apply-config --insecure` 對 Omni ISO 開機的機器行不通。**
原始 SOP 的第 1–3 步都打機器的 LAN IP。實測 `10.9.1.238` 的 `50000`／`50001`
**refused**——Omni ISO 開機的 Talos 只在 SideroLink 上開 API。改走 Omni 代理則
`apply-config` 回 `cluster "" endpoint not found`：**Omni 只替已在叢集裡的機器路由設定**。
所以那條路在這個組合下沒有可用的 API，而這正是為什麼要繞成「先建叢集」。

**二、「這個環境的 reset 清掉的比 STATE 多」是我的誤判。**
先前看到 `e755a600` 在 jgt-appliance 被拆之後 `installed=False`，我據此推論 reset 會連系統
一起清掉，並用它來質疑這條路。**這次證明系統會留下。** 那次的 False 另有原因，與 reset
的行為無關——**用量測的口氣說出推論，代價就是後面每個引用它的判斷都跟著歪。**

#### 還沒驗的

- **拔 USB 後的第一次冷開機**是在辦公室網路上完成的。客戶端網路（未知路由器、可能封鎖 UDP）
  仍未驗——那是 5.3，而 D12 的「一律開 gRPC tunnel」正是為它準備的
- 本次用的是舊 ISO（`omni-longhorn` preset、預設永不過期的 token、`client 1` 標籤），
  **不是出貨形狀**。短 TTL token 與 `ticket=` 標籤仍未在實機上走過一次

## Risks / Trade-offs

- **三題 intake 也可能太多** → D2 的實測會暴露；若實測顯示客戶答不出來，就再往 factory 側推（例如名稱自動產生）。
- **LINE 是第三方平台，訊息不受控** → 規格禁止任何金鑰材料經由該管道傳送。
- **紙本與線上內容可能分岔** → 要求同源產生，不允許手抄。
- **延後的三個診斷問題目前只能人工升級** → 明確標示，不假裝已解決；這是本 change 已知且接受的缺口。
- **App 可能永遠不做** → 因此 v0 必須自身可用，而不是「等 App 才完整」。目前四項能力已能涵蓋多數情境。
- **未受訓測試者不易取得** → 且用過一次就被污染，不能重複使用。需要事先規劃測試者來源。
- **文件正確性會再次腐化** → 修完現有四處錯誤只是一次性清理；長期需要把「文件指令是否存在」納入檢查，否則會重演。

## Migration Plan

1. 先修 `README.md` 的四處既有錯誤——與拆分無關，本身就是缺陷，先修可獨立驗證。
2. 拆分文件結構，內容先搬移不改寫，確認沒有遺漏。
3. 撰寫 `README-zero-IT.md`，並產出紙本版本。
4. 部署 onboarding bot 於 factory 側，先以 operator 自己當測試對象跑通。
5. 進行未受訓讀者實測，依結果修訂，重測至通過。
6. 第一台真實客戶交付時全程留痕，事後檢討。
7. **Rollback**：文件拆分可回復為單一 README；onboarding bot 停用後，溝通退回人工，不影響已交付叢集。

## Open Questions

- LINE Messaging API 接收圖片的流程與大小限制為何？影響「拍照診斷」是否可靠。
- 客戶在尚無叢集時如何與工單綁定？掃 QR 進來的人怎麼對應到正確的工單——是出貨時就發專屬連結，還是進來後問一個識別碼？
- 未受訓測試者從哪裡找？且每人只能用一次，需要幾人才算通過？
- 紙本 SOP 的產出流程為何（從 Markdown 產生印刷檔），如何確保改版後不會誤印舊版？
- rebinding protection 偵測在 v0（無 App）階段，能否用「請客戶在手機瀏覽器打開某個連結」這種低技術方式取得？若可以，② task 1.4 就不必等 App。

# Prisma SASE for Claude

[English](README.md) | **繁體中文**

給 Claude Desktop(Cowork)與 Claude Code 使用的唯讀 **Prisma SASE / Prisma
Access** 工具:一個 Python MCP server(6 個查詢工具)加上 `prisma-sase-ops`
Skill(工具決策樹、判讀閾值、診斷 runbook、週報模板)。安裝後可以直接對自己的
租戶問 Claude:*「現在 SASE 狀態如何?有沒有 P1 告警?」*、*「列出 tunnel
狀態,哪些斷線?」*。

一行指令就能裝好:

```bash
uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup
```

> **設計上即為唯讀** —— 整個專案不存在任何寫入 / commit / 推送設定的程式路徑。

## 關於本專案與免責聲明

本專案作者任職於 Palo Alto Networks,職務為 Solutions Consultant。
這是作者為了向客戶推廣 Prisma SASE、以個人時間開發的 **side project**:
**並非 Palo Alto Networks 官方開發、維護或背書,不代表公司立場;
內容與查詢結果亦不保證正確性、完整性或適用性** —— 使用前請自行評估,
重要決策請以官方文件與官方支援管道為準。本專案以開源方式發佈
(MIT License,見 [LICENSE](LICENSE)),歡迎透過 GitHub Issues / PR
提出任何意見與回饋,也歡迎**無償**引用、修改與再利用。

*Palo Alto Networks、Prisma 及相關標誌為 Palo Alto Networks, Inc. 之商標。*

## 內容物

刻意拆成兩半、分開安裝:

| 這一半 | 是什麼 | 怎麼裝 | 怎麼更新 |
|---|---|---|---|
| **MCP server** | 6 個唯讀查詢工具 | 一筆執行 `uvx` 的 **Local MCP server** 設定 | **自己更新** —— 每次啟動 app,uvx 都會重新解析本 repo |
| **`prisma-sase-ops` Skill** | 工具決策樹、判讀閾值、診斷 runbook、週報模板 | plugin marketplace | `/plugin marketplace update prisma-sase` |

在 0.9.0 之前這兩半是同一個 plugin。拆開的原因是 plugin 快取會**釘住版本**:
掛在 plugin 裡的 server 只有在使用者手動更新時才會變,而 uvx 那筆設定則是每次
app 啟動就抓一次現在的 `main`。會去打即時 API、必須保持最新的是 server;
Skill 是文字,慢一個版本不會傷到誰。

Server 單獨就能用 —— Skill 只是讓 Claude 更會挑工具、更會判讀回傳的數字。

想知道這 6 個工具對應到 PANW 完整 API 版圖的哪個位置(以及唯讀的 Phase 2
還能加什麼)?見
[Prisma SASE API catalog](plugin/skills/prisma-sase-ops/references/api-catalog.md)(英文)。

## 事前需求

| 需要 | 怎麼確認 | 缺少時怎麼裝 |
|---|---|---|
| **uv**(提供 `uvx`) | `uvx --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh`(macOS/Linux)或 `brew install uv`。Windows:`winget install astral-sh.uv`。完整說明:[docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **能連 GitHub 與 PyPI 的網路** | — | uvx 第一次啟動時抓本 repo 與兩個依賴套件,之後走快取。公司 proxy 環境:設 `HTTPS_PROXY=http://proxy:port` |
| **SCM 唯讀 service account** | — | 見下面的[產生 API Key](#產生-api-key建立唯讀-service-account) |

你**不需要**自己裝 Python。系統的版本太舊時 uv 會自己下載一個合用的 —— macOS
通常正是這種情況,內建的 `/usr/bin/python3` 常常是 3.9,而 `fastmcp` 需要 3.10。

還沒有 Prisma 租戶?一切都能離線試用:設 `PRISMA_MOCK=1`,所有工具會用
擬真範例資料回答 —— 不需要憑證、不需要網路。

## 安裝

**1. 產生 API Key** —— SCM 四步圖解在
[下一節](#產生-api-key建立唯讀-service-account)。做下一步之前,先把 Client ID
和 Client Secret 準備在手邊。

**2. 執行引導式設定。** 它會逐項說明並詢問那四個值,把 Client Secret 存進作業
系統的 keychain,然後幫你寫好 Local MCP servers 的設定:

```bash
uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup
```

寫入前它會先把整段設定顯示給你、並徵求同意;如果你比較想自己貼到
**Settings → Extensions → Local MCP servers**,加 `--print` 就只印不寫。
它產生的設定長這樣:

```json
{
  "command": "/opt/homebrew/bin/uvx",
  "args": ["--from", "git+https://github.com/eric2q/prisma-sase-plugin",
           "prisma-sase-mcp"],
  "env": {
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "PRISMA_CLIENT_ID": "apikey@**********.iam.panserviceaccount.com",
    "PRISMA_TSG_ID": "**********",
    "PRISMA_REGION": "sg",
    "PRISMA_SECRET_CMD": "security find-generic-password -s prisma-sase -a client_secret -w"
  }
}
```

請注意裡面**沒有** secret 本身。`PRISMA_SECRET_CMD` 是在啟動時才去 keychain
把它取出來。面板上的值是以**明文**存在 `claude_desktop_config.json`,而這個檔案
會跟著 Time Machine、以及任何會複製家目錄的備份一起被帶走 —— 所以 secret
不放進去。

**3. 完全重啟 Claude 應用程式**(macOS 按 ⌘Q —— 只關視窗不會重新啟動 MCP
server),然後就能開始問你的租戶狀況了。

**4. 選用 —— 加裝 Skill**,取得診斷 runbook 與週報模板:

*Claude Desktop / Cowork:* **Settings → Plugins → Add marketplace → Add from a
repository** → 輸入 `eric2q/prisma-sase-plugin` → 安裝 **prisma-sase**。

*Claude Code(CLI):*

```
/plugin marketplace add eric2q/prisma-sase-plugin
/plugin install prisma-sase@prisma-sase
```

> **沒有 uv,也裝不了?** 還有一條只需要 Python ≥ 3.10 的 venv 備援路徑:
> clone 本 repo 後執行 `bash src/prisma_sase_mcp/install.sh`
> (Windows:`src\prisma_sase_mcp\install.bat`),再把 Local MCP 設定指向
> `run.sh`。功能完全一樣,但**不會自動更新** —— repo 要自己 pull。細節見
> [`plugin/README.md`](plugin/README.md)(英文)。

## 產生 API Key(建立唯讀 Service Account)

Prisma SASE 的「API key」就是一組 Service Account 的 **Client ID + Client
Secret**,在 **Strata Cloud Manager(SCM)** 建立,共四步。本 plugin 只需
**唯讀**權限 —— 這是資安要求,也是設計保證(工具層不存在任何寫入路徑)。

> 本節示意圖依實際操作截圖重繪(版面、欄位、警語忠於原畫面),租戶識別值
> 已遮罩。紅色標號為全流程連續編號:① 齒輪 → ② IAM → ③ 取名 →
> ④ Client ID → ⑤ Client Secret。

**步驟 1 —— 進入 Identity & Access Management。** SCM 左側欄最下方的齒輪
圖示(**System Settings**,①)→ 選單第一項 **Identity & Access Management**
(②),再點 **Add Identity** 開啟「Add New Identity」三步精靈
(Identity Information → Client Credentials → Assign Roles)。

<img src="plugin/docs/images/scm-1-iam-menu.png" alt="SCM 左側選單:① 齒輪(System Settings)→ ② Identity & Access Management" width="420">

**步驟 2 —— Identity Information(身分資訊)。** Identity Type 選
**Service Account**;Service Account Name(③)取一個好認的名稱(例如
`apikey` 或 `claude-mcp-readonly` —— 此名稱會成為 Client ID 的前綴);
Contact 與 Description 為選填 → **Next**。

<img src="plugin/docs/images/scm-2-identity-info.png" alt="Add New Identity — Identity Information:Identity Type = Service Account;③ 取名" width="640">

**步驟 3 —— Client Credentials(取得憑證,最關鍵的一步)。** 系統當場產生
兩個值:**Client ID**(④)與 **Client Secret**(⑤)。

⚠️ **Client Secret 只顯示這一次** —— 畫面警語原文:「Please save the Client
Secret, you will not be able to copy it after saving the new identity.」請立刻
用複製鈕存下,或按 **Download CSV File** 下載(CSV 內含 secret,存入密碼
管理器後請刪除檔案)。忘了存,只能之後對此帳號重新產生 secret(輪替)再
更新憑證檔。TSG ID 不用另外查 —— **Client ID 中 `@` 之後的那串數字就是
TSG ID**。→ **Next**。

<img src="plugin/docs/images/scm-3-client-credentials.png" alt="Client Credentials:④ Client ID(@ 後數字即 TSG)、⑤ Client Secret(僅此一次顯示;可 Download CSV File)" width="640">

**步驟 4 —— Assign Roles(指派唯讀角色)。** 此頁標示 Optional,**但務必
要做** —— 沒有指派角色的 service account 沒有任何權限,plugin 會收到 403。
Apps & Services 選 **All Apps & Services**,Role 選 **View Only
Administrator** → **Submit** 完成。View Only Administrator 已足夠本 plugin
全部功能;請勿授予 Superuser 等可寫角色(最小權限原則)。系統中雖有更細的
角色(如 ADEM Tier 1 Support、Multitenant Monitor User),但無法同時涵蓋
Insights 與 ADEM 兩組 API —— View Only Administrator 是已確認的最合適
標準配置。多租戶(MSP)環境請留意 identity 建在正確的 TSG 範圍下,
scope 只綁必要租戶。

<img src="plugin/docs/images/scm-4-assign-roles.png" alt="Assign Roles:All Apps & Services + View Only Administrator → Submit" width="640">

**提供步驟 3 記下的值** —— 三條支援路徑,由好到次:

- **`prisma-sase-setup`(建議用這條):** 就是[安裝](#安裝)步驟 2 的引導式設定。
  Secret 進作業系統 keychain,另外三個值進 Local MCP 設定,再加一條啟動時去
  取 secret 的 `PRISMA_SECRET_CMD`。不會有任何機密被寫進檔案。
- **自己填 Local MCP servers 面板:** 同樣那四個值,當成環境變數填。簡單,
  而且多數 MCP server 都是這樣做 —— 但 `PRISMA_CLIENT_SECRET` 就會以明文
  躺在 `claude_desktop_config.json` 裡。自己的實驗租戶無妨;客戶的租戶請三思。
- **憑證檔**(`~/.prisma-sase.env`,KEY=VALUE、不需引號;下例以星號遮罩)——
  給 venv 備援路徑、雲端 session 與 CI 用:

  ```
  PRISMA_CLIENT_ID=apikey@**********.iam.panserviceaccount.com
  PRISMA_CLIENT_SECRET=********************************
  PRISMA_TSG_ID=**********
  PRISMA_REGION=sg
  ```

  Secret 那行也可以改成指向密碼管理器、讓整個檔案變成非機密:
  `PRISMA_SECRET_CMD=security find-generic-password -s prisma-sase -a client_secret -w`
  (`secret-tool`、`pass`、`op read` 也都適用)。

`PRISMA_TSG_ID` 就是 Client ID 中 `@` 之後的數字(引導式設定會自動幫你抓出
來);`PRISMA_REGION` 填租戶實際 region(例如 `sg`、`us`、`de`)。填完重啟
Claude 應用程式。想在不洩漏內容的前提下確認存了什麼:
`uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup --show`。

**存放原則:** 憑證只存在於受支援的存放地之一 —— 作業系統 keychain
(透過 `PRISMA_SECRET_CMD`)、面板設定、或本機憑證檔(`chmod 600`)—— 此外
**哪裡都不放**。不要提交進任何 repo、不要在專案資料夾留副本、不要把
secret 貼到任何地方;雲端 session 用暫時工作副本、用完即刪
(見 [`plugin/README.md`](plugin/README.md) 的 "Cloud sessions" 一節)。

> ⚠️ **Client Secret 請勿貼進任何對話、聊天視窗或文件** —— 工具刻意不提供
> 憑證參數,憑證只進本機憑證檔。若 secret 曾外流,請立即在 SCM 輪替,
> 並更新憑證檔。

## 如果 SASE 工具沒出現

依序試這三招:

1. **自己在終端機把 server 跑起來** —— 它會印出到底找到了什麼,而且不會印出
   任何憑證值:

   ```bash
   uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-mcp --selfcheck
   ```

   最常見的原因是 `PATH` 上找不到 `uvx`:app 不會把登入 shell 的 `PATH` 傳給
   MCP server,這也正是產生出來的設定要明確帶一份 `PATH` 的理由。如果
   `which uvx` 印出來的位置不在那份清單裡,請把它加進去。
2. **請 Claude 執行 `prisma_sase_setup_required`。** 真正的 server 起不來
   時,會由一個零依賴的替補 server 頂上,這個工具會回傳診斷結果與可直接
   複製的修復指令。
3. **查看 `~/.prisma-sase-launch.log`** —— 啟動軌跡,記錄選用了哪個直譯器
   以及確切死因(**檔案完全不存在 = host 根本沒啟動 server**)。逐行判讀表:
   [`plugin/README.md`](plugin/README.md#if-the-tools-dont-show-up)(英文)。

修好之後,請**完全重啟 Claude 應用程式**(macOS 按 ⌘Q —— 只關視窗不會重新
啟動 MCP server)。

## 更新

**Server 會自己更新。** Local MCP 設定跑的是沒有釘任何 git ref 的
`uvx --from git+…`,所以每次 app 啟動都會重新解析本 repo 的 `main`,commit
有變就重新建置。維護者推送 → 你重開 app → 你就是最新版,不必按任何按鈕。
(想確認自己跑的是哪一版,問一下 SASE 狀態即可 —— 回應裡會帶 `plugin_version`。)

**Skill 不會。** plugin 是按版本快取的,只有你說了才會動:

```
/plugin marketplace update prisma-sase
```

Desktop 則是 **Settings → Plugins →(該 marketplace)Update**。版本由
`.claude-plugin/marketplace.json` 的 `version` 欄位釘住 —— 該欄位變更時使用者
才會看到更新(見 [`PUBLISHING.md`](PUBLISHING.md))。

**每一版改了什麼** —— 修了哪些 bug、新增哪些功能、行為有什麼變化 —— 都逐版
記錄在 [`plugin/CHANGELOG.md`](plugin/CHANGELOG.md)(條目標記
`FIX` / `NEW` / `CHG`,英文)。

**需要固定版本的話。** 在 `--from` 的 URL 後面加上 git ref,自動更新就停在
那裡:`git+https://github.com/eric2q/prisma-sase-plugin@v0.9.0`。要對客戶
demo、不希望腳下的東西自己移動時很有用。

## 關於託管方式

本 repository 是**公開**的 —— `uvx` 匿名就能 clone,任何人不需 GitHub 認證
即可加入 marketplace,兩條更新路徑都直接可用。

如果你 fork 之後改以**私有** repo 託管:`uvx` 會走你的 git credential helper,
所以 `gh auth setup-git`(或用 `git+ssh://git@github.com/...` 這種 SSH remote
搭配已載入金鑰的 `ssh-agent`)對 server 來說就夠了。Skill 這邊,手動加入 /
更新走的是同一組認證,但私有 repo 走 HTTPS 的背景自動更新在設計上有限制 ——
請設定 `CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE=1`,讓背景更新失敗時
保留現有工作副本。

## Repo 結構

```
src/prisma_sase_mcp/              # MCP server —— uvx 建置與執行的就是這個
src/prisma_sase_mcp/setup_wizard.py   # `prisma-sase-setup` 引導式安裝程式
src/prisma_sase_mcp/install.sh    # 沒有 uv 的環境用的 venv 備援
pyproject.toml                    # 進入點:prisma-sase-mcp、prisma-sase-setup
plugin/                           # 只放 Skill,別無他物
plugin/CHANGELOG.md               # 版本歷史:每一版的 bug 修正與新功能
.claude-plugin/marketplace.json   # 目錄:一個項目,就是 Skill
tools/build-standalone.py         # 選用:建置離線 .plugin 檔(供「Upload from file」安裝)
PUBLISHING.md                     # 維護者發佈流程
README.zh-TW.md                   # 本頁(繁體中文版)
```

連不到 marketplace 的機器仍可隨時建置獨立的 `.plugin` 檔:
`python3 tools/build-standalone.py` → `dist/`。它只帶 Skill,而且不會自己更新。

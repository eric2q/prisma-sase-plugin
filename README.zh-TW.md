# Prisma SASE Plugin Marketplace

[English](README.md) | **繁體中文**

給 Claude Desktop(Cowork)與 Claude Code 使用的唯讀 **Prisma SASE / Prisma
Access** 工具:一個 Python MCP server(6 個查詢工具)加上 `prisma-sase-ops`
Skill(工具決策樹、判讀閾值、診斷 runbook、週報模板)。安裝後可以直接對自己的
租戶問 Claude:*「現在 SASE 狀態如何?有沒有 P1 告警?」*、*「列出 tunnel
狀態,哪些斷線?」*。

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

本 repo 是一個 **plugin marketplace**:單一程式樹(`plugin/`),三個 OS 專屬的
目錄項,差別只在啟動 server 的方式。請安裝符合你作業系統的那一個:

| 你的作業系統 | 安裝這個 plugin | 啟動器 |
|---|---|---|
| macOS | **`prisma-sase-mac`** | `bash mcp/run.sh` |
| Linux | **`prisma-sase-linux`** | `bash mcp/run.sh` |
| Windows | **`prisma-sase-windows`** | `cmd /c mcp\run.cmd` |

想知道這 6 個工具對應到 PANW 完整 API 版圖的哪個位置(以及唯讀的 Phase 2
還能加什麼)?見
[Prisma SASE API catalog](plugin/skills/prisma-sase-ops/references/api-catalog.md)(英文)。

## 事前需求

安裝前環境需要的東西都在下表。**不確定自己有沒有?直接執行安裝腳本(下面
步驟 1)就好** —— 腳本會逐項檢查,缺什麼就依你的作業系統印出確切的安裝
指令,照著做完再跑一次即可(重複執行是安全的)。

| 需要 | 怎麼確認 | 缺少時怎麼裝 |
|---|---|---|
| **Python ≥ 3.10** | `python3 --version`(Windows:`py --version` 或 `python --version`) | macOS:`brew install python@3.12` 或 [python.org](https://www.python.org/downloads/) 安裝程式。Debian/Ubuntu:`sudo apt install python3 python3-venv python3-pip`。Fedora/RHEL:`sudo dnf install python3`。Windows:[python.org](https://www.python.org/downloads/) 安裝程式 —— 記得勾選 **"Add python.exe to PATH"** |
| **venv + pip**(通常隨 Python 附帶) | `python3 -m venv --help` | Debian/Ubuntu 拆成獨立套件:`sudo apt install python3-venv python3-pip`;其他平台隨 Python 一起裝好 |
| **能連 PyPI 的網路**(一次性) | — | 安裝腳本需要下載一次 `fastmcp` + `httpx`。公司 proxy 環境:先設 `HTTPS_PROXY=http://proxy:port` 再執行腳本 |
| **git**(僅 marketplace 安裝需要) | `git --version` | macOS:`xcode-select --install`。Linux:`sudo apt install git` / `sudo dnf install git`。Windows:[git-scm.com](https://git-scm.com/)。完全沒有 git?改用獨立 `.plugin` 檔安裝(見 [Repo 結構](#repo-結構)) |

⚠️ 兩個常見陷阱(腳本也會偵測並說明):
- **macOS**:內建的 `/usr/bin/python3` 常常是 **3.9** —— 太舊不能用。裝一個
  新版即可,腳本會自動找到它。
- **Windows**:如果打 `python` 會打開 **Microsoft Store**,那是別名假捷徑、
  不是真的 Python。請到 python.org 安裝正式版(勾 "Add to PATH"),或關閉
  該別名(設定 → 應用程式 → 進階應用程式設定 → 應用程式執行別名)。

還沒有 Prisma 租戶?一切都能離線試用:設 `PRISMA_MOCK=1`,所有工具會用
擬真範例資料回答 —— 不需要憑證、不需要網路。

## 安裝

**1. 每台機器一次性設定**(Python ≥ 3.10 + venv + 依賴套件 + 憑證範本檔)。
把這個 repo clone 或下載到任意暫存位置後執行:

```bash
# macOS / Linux
bash plugin/install.sh
```
```bat
:: Windows(請先到 python.org 安裝 Python,並勾選 "Add python.exe to PATH")
plugin\install.bat
```

**2. 加入 marketplace 並安裝 plugin。**

*Claude Desktop / Cowork:* **Settings → Plugins → Add marketplace → Add from a
repository** → 輸入本 repo(`eric2q/prisma-sase-plugin` 或完整 git URL)→ 依你的
OS 安裝 **prisma-sase-mac**、**prisma-sase-linux** 或 **prisma-sase-windows**。

*Claude Code(CLI):*

```
/plugin marketplace add eric2q/prisma-sase-plugin
/plugin install prisma-sase-mac@prisma-sase      # macOS
/plugin install prisma-sase-linux@prisma-sase    # Linux
/plugin install prisma-sase-windows@prisma-sase  # Windows
```

**3. 憑證 —— 產生 API Key**(完整圖解見下一節),然後提供四個值。
**啟用 plugin 時會跳出表單直接問你** —— Claude Desktop 與 Claude Code CLI
都會問(Client Secret 輸入時遮罩,存進安全儲存區,不進 `settings.json`),
請走這條路。`~/.prisma-sase.env`(Windows:`%USERPROFILE%\.prisma-sase.env`;
範本已由安裝腳本建立)是備援 —— 雲端 session、CI、或沒有表單的環境走這條,
表單沒涵蓋的選用調校變數也放這裡。填完後重啟 Claude 應用程式。
更多細節、selfcheck 與疑難排解請見:[`plugin/README.md`](plugin/README.md)
(英文)。

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

**提供步驟 3 記下的值** —— 兩條支援路徑:

- **Plugin 啟用表單(建議用這條):** 安裝/啟用 plugin 時,Claude 會跳出表單問
  Client ID、Client Secret、TSG ID、Region —— Claude Desktop 與 Claude Code
  CLI 都支援。Secret 輸入時遮罩,存進**安全儲存區**(macOS Keychain;沒有
  可用 keychain 的平台則是 `~/.claude/.credentials.json`),不進
  `settings.json`,也不落我們的任何檔案。
- **憑證檔**(`~/.prisma-sase.env`,KEY=VALUE、不需引號;下例以星號遮罩)——
  備援路徑,雲端 session、CI、或沒有表單的環境用:

  ```
  PRISMA_CLIENT_ID=apikey@**********.iam.panserviceaccount.com
  PRISMA_CLIENT_SECRET=********************************
  PRISMA_TSG_ID=**********
  PRISMA_REGION=sg
  ```

  Secret 那行也可以改成指向密碼管理器、讓整個檔案變成非機密:
  `PRISMA_SECRET_CMD=security find-generic-password -s prisma-sase -w`
  (`secret-tool`、`pass`、`op read` 也都適用)。

`PRISMA_TSG_ID` 就是 Client ID 中 `@` 之後的數字;`PRISMA_REGION` 填租戶
實際 region(例如 `sg`、`us`、`de`)。填完重啟 Claude 應用程式,並可用
server 的 `--selfcheck` 驗證 —— 它會顯示 secret 來自哪個來源。

**存放原則:** 憑證只存在於受支援的存放地之一 —— 作業系統安全儲存區
(啟用表單 / `PRISMA_SECRET_CMD`)或本機憑證檔(`chmod 600`)—— 此外
**哪裡都不放**。不要提交進任何 repo、不要在專案資料夾留副本、不要把
secret 貼到任何地方;雲端 session 用暫時工作副本、用完即刪
(見 [`plugin/README.md`](plugin/README.md) 的 "Cloud sessions" 一節)。

> ⚠️ **Client Secret 請勿貼進任何對話、聊天視窗或文件** —— 工具刻意不提供
> 憑證參數,憑證只進本機憑證檔。若 secret 曾外流,請立即在 SCM 輪替,
> 並更新憑證檔。

## 如果 SASE 工具沒出現

依序試這兩招 —— 專為「plugin 看起來裝好了,但對話裡完全沒有 Prisma SASE
工具」這個情境設計:

1. **請 Claude 執行 `prisma_sase_setup_required`。** 真正的 server 起不來
   時,會由一個零依賴的替補 server 頂上,這個工具會回傳診斷結果與可直接
   複製的修復指令。
2. **查看 `~/.prisma-sase-launch.log`** —— 啟動軌跡,記錄選用了哪個直譯器
   以及確切死因(**檔案完全不存在 = host 根本沒啟動 server**)。逐行判讀表:
   [`plugin/README.md`](plugin/README.md#if-the-tools-dont-show-up-two-places-to-look)(英文)。

修好之後,請**完全重啟 Claude 應用程式**(macOS 按 ⌘Q —— 只關視窗不會重新
啟動 plugin server)。

## 更新

維護者推送到本 repo 後,使用者在 Desktop 用
**Settings → Plugins →(該 marketplace)Update** 取得更新,或:

```
/plugin marketplace update prisma-sase
```

Claude Code 也會在背景自動刷新 marketplace。版本由
`.claude-plugin/marketplace.json` 的 `version` 欄位釘住 —— 該欄位變更時使用者
才會看到更新(見 [`PUBLISHING.md`](PUBLISHING.md))。

**每一版改了什麼** —— 修了哪些 bug、新增哪些功能、行為有什麼變化 —— 都逐版
記錄在 [`plugin/CHANGELOG.md`](plugin/CHANGELOG.md)(條目標記
`FIX` / `NEW` / `CHG`,英文)。

## 關於託管方式

本 repository 是**公開**的 —— 任何人不需 GitHub 認證即可加入 marketplace 並
安裝,背景自動更新也直接可用。

如果你 fork 之後改以**私有** repo 託管:手動加入 / 更新會走你平常的 git 認證
(`gh auth setup-git`、SSH agent),但私有 repo 走 HTTPS 的背景自動更新在設計上
有限制 —— 請在每台機器執行 `gh auth setup-git`,並設定
`CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE=1`,讓背景更新失敗時保留現有
工作副本。使用 SSH remote 且 `ssh-agent` 已載入金鑰的話,自動更新沒有問題。

## Repo 結構

```
.claude-plugin/marketplace.json   # 目錄:3 個 OS 專屬項目,共用同一程式樹、各自的啟動器
plugin/                           # 單一程式樹(server + skills + 安裝腳本)
plugin/CHANGELOG.md               # 版本歷史:每一版的 bug 修正與新功能
tools/build-standalone.py         # 選用:建置離線 .plugin 檔(供「Upload from file」安裝)
PUBLISHING.md                     # 維護者發佈流程
README.zh-TW.md                   # 本頁(繁體中文版)
```

無法連 git 的機器仍可隨時建置獨立的 `.plugin` 檔:
`python3 tools/build-standalone.py` → `dist/`。

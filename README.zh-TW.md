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

**3. 填入憑證** —— 編輯 `~/.prisma-sase.env`(Windows:
`%USERPROFILE%\.prisma-sase.env`;範本已由安裝腳本建立)。四個值:
`PRISMA_CLIENT_ID`、`PRISMA_CLIENT_SECRET`、`PRISMA_TSG_ID`、
`PRISMA_REGION`。填完後重啟 Claude 應用程式。完整細節、service account
建立步驟、selfcheck 與疑難排解請見:[`plugin/README.md`](plugin/README.md)
(英文)。

## 更新

維護者推送到本 repo 後,使用者在 Desktop 用
**Settings → Plugins →(該 marketplace)Update** 取得更新,或:

```
/plugin marketplace update prisma-sase
```

Claude Code 也會在背景自動刷新 marketplace。版本由
`.claude-plugin/marketplace.json` 的 `version` 欄位釘住 —— 該欄位變更時使用者
才會看到更新(見 [`PUBLISHING.md`](PUBLISHING.md))。

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
tools/build-standalone.py         # 選用:建置離線 .plugin 檔(供「Upload from file」安裝)
PUBLISHING.md                     # 維護者發佈流程
README.zh-TW.md                   # 本頁(繁體中文版)
```

無法連 git 的機器仍可隨時建置獨立的 `.plugin` 檔:
`python3 tools/build-standalone.py` → `dist/`。

# Group Meeting 簡報自動摘要 Agent

每週三 08:30 掃描 Mattermost 頻道，找出本週分享的簡報，產生「非本科系也看得懂」的圖文摘要，回覆在原貼文的討論串。

## 協作文件

兩個人各自用 Claude 開發，以下三份文件是對齊進度的依據。`CLAUDE.md` 會要求 Claude 每次工作前先讀、結束前更新。

| 文件 | 內容 |
| --- | --- |
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | 所有需求與目前狀態 |
| [`docs/STATUS.md`](docs/STATUS.md) | 誰在做什麼、待辦、進度紀錄 |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 已經決定的設計取捨 |

## 需求

- Python 3.10 以上（只用標準函式庫；3.10 另需 `sudo apt install python3-tomli`）
- poppler-utils：`sudo apt install poppler-utils`
- Claude Code CLI，已用訂閱帳號登入
- 選用：LibreOffice（PPTX 附件）、Chromium（HTML 附件）、Ollama（本地備援）

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `main.py` | 主流程：抓貼文、去重、發文、回報 |
| `sources.py` | 找出簡報、匯出 PDF、轉成逐頁 PNG |
| `summary_harness.py` | 提示詞、呼叫模型、驗證與重試 |
| `mattermost.py` | Mattermost API 用戶端 |
| `store.py` | SQLite 處理狀態 |
| `config.example.toml` | 設定範本 |
| `tests/test_pipeline.py` | 端到端測試（假伺服器，不需網路） |
| `tools/live_check.py` | 真實環境檢查，輸出不含內容的報告 |
| `.github/workflows/` | 自動測試；結果寫到 `ci-results` 分支 |
| `docs/RUNNER_SETUP.md` | 自架 runner 的一次性設定 |

## 設定

1. `cp config.example.toml config.toml`，填入 `base_url`、`channel_id`、`test_channel_id`、`maintainer_username`。
2. 請 Mattermost 管理員建立 Bot 帳號，把 Bot 加進正式頻道和測試頻道。
3. 把 Bot token 存成檔案並 `chmod 600`，路徑填到 `token_file`；或用環境變數 `MM_BOT_TOKEN`。
4. 隔離方式二擇一：
   - 整支程式用一個專用低權限帳號跑：`allow_direct = true`、`isolation_user = ""`。設定最簡單，建議先用這個。
   - 主程式和 Claude 分開帳號：填 `isolation_user`，並在 sudoers 放行，主程式帳號要加入該帳號的群組。

## 建議的測試順序

每一步都過了再往下。

```bash
# 0. 本機邏輯測試（不碰任何外部服務）
python3 tests/test_pipeline.py

# 1. 測 Mattermost 與 Google 匯出，不呼叫模型、不發文
python3 main.py --config config.toml --dry-run --fake-llm --since-hours 720
#    看 dryrun_out/：每則簡報貼文應有一個 .md 和幾張 PNG；_report.md 列出沒開權限的

# 2. 確認 Claude CLI 參數（summary_harness.py 用到這三個）
claude -p --system-prompt '只輸出 {"ok": true}' --allowedTools Read --output-format json <<< "輸出 JSON"
claude -p --system-prompt '只輸出 {"ok": true}' --tools "" --output-format json <<< "輸出 JSON"

# 3. 用真的模型跑，仍不發文；看摘要品質與日誌中的耗時
python3 main.py --config config.toml --dry-run --since-hours 720

# 4. 發到測試頻道（reply_mode = "test_channel"）
python3 main.py --config config.toml --since-hours 168

# 5. 試跑兩週沒問題後，把 reply_mode 改成 "thread" 正式上線
```

第 3 步請記下一份 30 頁左右簡報的實際耗時，把 `vision_timeout_sec` 設成兩倍。

## 排程

```cron
CRON_TZ=Asia/Taipei
30 8 * * 3  cd /opt/lab-summarizer && /usr/bin/python3 main.py --config config.toml >> /var/log/lab-summarizer.log 2>&1
```

## 行為摘要

- **掃描範圍**：上週三 12:00 到執行當下的主貼文。
- **算作簡報**：Google Slides 連結（含藏在 Markdown 超連結裡的），以及 PDF、PPTX 附件。
- **會跳過**：公告、預告、只有 GitHub 或試算表連結、影片附件、系統訊息、Bot 自己的貼文、含 `#no-summary` 的貼文。
- **去重**：以貼文 ID 為準。同一份簡報隔週重貼會重新摘要。
- **沒開權限**：在討論串回一行請講者開啟檢視權限，之後不再處理該則。
- **模型失敗**：不在頻道發任何東西，私訊維護者。
- **執行結果**：每次有動作都會私訊維護者一則統計，含失敗原因代碼。
- **日誌**：只有貼文 ID、狀態碼、字數與耗時，不含簡報內容。

## 尚未在真實環境驗證

以下幾項在開發時無法實測，第一次跑請特別留意：

1. Mattermost 的讀取、上傳與發文（目前只對假伺服器測過）。
2. Google Slides 免登入匯出 PDF（`/export/pdf`）對原生簡報與上傳的 .pptx 是否都可用。
3. 真實簡報的摘要品質與耗時（目前只用合成的英文測試簡報跑過 Claude CLI）。
4. Ollama 備援（預設關閉）。

## 已知限制

- HTML 附件預設關閉。開啟後會用無頭瀏覽器執行附件內的 JavaScript，請先評估風險。
- 簡報超過 32 頁時 Claude 只看抽樣的 32 頁（前兩頁、最後兩頁一定保留）。
- Claude 的登入憑證與 Read 工具在同一個帳號下。輸出有做憑證特徵掃描，但無法擋住刻意編碼的外洩，所以執行帳號裡不要放其他機密。

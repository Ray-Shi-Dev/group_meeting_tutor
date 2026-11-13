# 自架 runner 設定（只需要做一次）

這份文件給「握有 Mattermost token 的那台機器」的管理者。做完之後，雙方的 Claude 就能自己觸發真實環境檢查並讀回結果，token 不會離開這台機器。

## 運作方式

1. 有人修改 `.ci/live-request` 並推到 `main`。
2. 這台機器上的 runner 執行 `tools/live_check.py`，用本機的設定檔和 token 跑 `main.py`。
3. 不含內容的報告寫到 `ci-results` 分支的 `results/live.md`。
4. 摘要本身只留在這台機器的 `~/.config/lab-summarizer/last_dryrun/`，或發到測試頻道。

報告只有環境檢查、狀態碼、貼文 ID、頁數、字數與耗時。Token、網址、頻道 ID、簡報與摘要內容都不會上傳。

## 開始之前

- **repo 必須是私人的。** 自架 runner 會在你的機器上執行 repo 裡的程式，GitHub 官方不建議用在公開 repo。
- **用專屬 Bot 帳號的 token，不要用個人 token。** 有 repo 寫入權的人都能讓程式在 runner 上執行，等於拿得到這個 token，所以它的權限要盡量小：Bot 只加入 group meeting 頻道和測試頻道。
- Token 不要貼到任何對話、issue 或檔案裡。外洩時請管理員撤銷重發。

## 步驟

### 1. 安裝工具

```bash
sudo apt update
sudo apt install -y git poppler-utils python3-tomli
```

`python3 --version` 需要 3.10 以上。要支援 PPTX 附件再加裝 `libreoffice-impress`。

### 2. 放設定檔與 token

```bash
mkdir -p ~/.config/lab-summarizer && chmod 700 ~/.config/lab-summarizer
cd ~/.config/lab-summarizer
# 把 Bot token 存成檔案（用編輯器貼上，不要用 echo，避免留在 shell 歷史紀錄）
nano mm_token && chmod 600 mm_token
# 從 repo 複製 config.example.toml 過來改名為 config.toml，然後填寫
```

`config.toml` 要填的欄位：

| 欄位 | 填什麼 |
| --- | --- |
| `base_url` | Mattermost 網址 |
| `channel_id` | group meeting 頻道 ID |
| `test_channel_id` | 測試頻道 ID |
| `token_file` | `mm_token` 的絕對路徑 |
| `maintainer_username` | 接收執行結果私訊的帳號 |
| `reply_mode` | 保持 `test_channel` |
| `claude_bin` | `which claude` 的結果 |
| `isolation_user`、`allow_direct` | 整台機器只跑這個用途時：`isolation_user = ""`、`allow_direct = true` |
| `db_path` | 例如 `/home/你的帳號/.config/lab-summarizer/state.sqlite3` |

### 3. 安裝並登入 Claude CLI

依官方文件安裝 Claude Code，執行一次 `claude` 完成登入。

### 4. 先在本機確認

還沒裝 runner 也可以先跑這一行。輸出不含任何機密，可以直接貼給 Claude：

```bash
git clone https://github.com/Ray-Shi-Dev/group_meeting_tutor.git && cd group_meeting_tutor
python3 tools/live_check.py --config ~/.config/lab-summarizer/config.toml --mode dryrun-fake --since-hours 1440 --result -
```

### 5. 註冊 runner

到 repo 的 Settings → Actions → Runners → New self-hosted runner，選 Linux，照頁面上的指令下載與設定。執行 `./config.sh` 時：

- 問到 labels 時輸入 `lab-summarizer`（workflow 靠這個標籤找到這台機器）。
- 其他都按 Enter 用預設值。

然後讓它常駐：

```bash
sudo ./svc.sh install && sudo ./svc.sh start
```

WSL 沒有啟用 systemd 時改用 `./run.sh`，放在 tmux 裡執行；電腦關機或睡眠時 runner 就離線，請求會排隊到它回來。

### 6. 觸發第一次檢查

把 `.ci/live-request` 裡的 `request` 數字加一並推到 `main`，或告訴 Claude「runner 裝好了」。幾分鐘後 `ci-results` 分支會出現 `results/live.md`。

## 三種檢查模式

| 模式 | 發文 | 呼叫模型 | 用途 |
| --- | --- | --- | --- |
| `dryrun-fake` | 否 | 否 | 確認讀得到頻道、簡報匯得出來 |
| `dryrun-real` | 否 | 是 | 產生真的摘要，留在本機給人看 |
| `test-channel` | 只發測試頻道 | 是 | 完整流程；程式會強制忽略 `reply_mode`，不會發到正式頻道 |

## 停用

```bash
sudo ./svc.sh stop && sudo ./svc.sh uninstall
./config.sh remove
```

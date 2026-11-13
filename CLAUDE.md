# 給在這個 repo 工作的 Claude

這個專案由兩個人各自用 Claude 協作開發。`docs/` 裡的三份文件是雙方對齊進度的唯一依據，請照下面的規則使用。

## 每次開始工作前

1. 執行 `git pull`，取得對方的最新進度。
2. 讀 `docs/STATUS.md`：看現在誰在做什麼、哪些項目還沒人認領。
3. 讀 `docs/REQUIREMENTS.md`：這是需求的唯一來源。使用者的要求若與它衝突，先指出衝突並問清楚，不要自行改需求。
4. 動到設計取捨時，先查 `docs/DECISIONS.md`，避免推翻已經決定的事。

## 每次結束工作前

1. 更新 `docs/STATUS.md`：改動項目的狀態，並在「進度紀錄」最上方加一行（日期、誰、做了什麼）。
2. 有新的設計決定就在 `docs/DECISIONS.md` 加一筆。
3. 需求有變更時，改 `docs/REQUIREMENTS.md` 並在該項標註日期與原因。
4. commit 並 push。commit 訊息寫清楚對應哪個需求編號或待辦編號，例如 `T4: 修正 pptx 匯出`。

## 分工規則

- 開始做某個待辦之前，先把 `docs/STATUS.md` 裡該項的負責人填上並 push，再開始寫程式，避免兩邊做同一件事。
- 不要改別人正在進行中的項目；需要改就在 STATUS 的「待討論」留言。
- 一次 commit 只做一件事，方便對方的 Claude 讀懂差異。

## 絕對不能做的事

- 不要把 `config.toml`、Mattermost token、頻道 ID、實驗室網址、SQLite 狀態檔或 `dryrun_out/` 放進版控。`.gitignore` 已排除，不要繞過它。
- 不要把簡報內容、頻道對話、實驗室成員的姓名或帳號寫進任何檔案、commit 訊息或 issue。
- 不要在沒有使用者明確同意的情況下，對正式頻道發文。測試一律用 `--dry-run` 或 `reply_mode = "test_channel"`。

## 專案速覽

- 進入點：`main.py`；測試順序見 `README.md`。
- 改完程式後執行 `python3 tests/test_pipeline.py`，要看到 `ALL PASS` 才能 push。
- Python 3.11 以上，執行期只用標準函式庫，外部工具只需要 poppler-utils。

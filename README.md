# Group Meeting Slide Summary Agent

Every Wednesday at 08:30 the agent scans a Mattermost channel, finds the slide decks shared for that week's group meeting, and replies under each post with an illustrated summary that someone outside the field can follow.

The summaries and everything posted to Mattermost are in Traditional Chinese. The repo itself is in English.

## Working together

Two people develop this, each with their own Claude. These files keep both sides aligned; `CLAUDE.md` tells Claude to read them before working and update them afterwards.

| File | Contents |
| --- | --- |
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | Every requirement and its current state |
| [`docs/STATUS.md`](docs/STATUS.md) | Who is doing what, the task list, the progress log |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Design decisions that are already settled |
| [`docs/SETUP.md`](docs/SETUP.md) | One-time setup on the machine that holds the token |

## Requirements

- Python 3.10 or newer (standard library only; 3.10 also needs `sudo apt install python3-tomli`)
- poppler-utils: `sudo apt install poppler-utils`
- Claude Code CLI, signed in with a subscription account
- Optional: LibreOffice (PPTX attachments), Chromium (HTML attachments), Ollama (local fallback)

## Files

| File | Purpose |
| --- | --- |
| `main.py` | Pipeline: fetch posts, dedupe, post replies, report |
| `sources.py` | Find decks, export to PDF, render pages to PNG |
| `summary_harness.py` | Prompts, model calls, validation and retries |
| `mattermost.py` | Mattermost API client |
| `store.py` | Processing state in SQLite |
| `config.example.toml` | Config template |
| `tools/mm_setup.py` | One-time Mattermost setup: test channel, bot, token file, config |
| `tools/live_check.py` | Live environment check with a content-free report |
| `tests/` | End-to-end tests against fake servers (no network needed) |
| `.github/workflows/` | Automated tests; results go to the `ci-results` branch |

## Getting started

Follow [`docs/SETUP.md`](docs/SETUP.md). In short:

```bash
sudo apt install -y git poppler-utils python3-tomli
git clone https://github.com/Ray-Shi-Dev/group_meeting_tutor.git && cd group_meeting_tutor
python3 tools/mm_setup.py          # asks for the channel URL and your token, sets up the rest
python3 tools/live_check.py --config ~/.config/lab-summarizer/config.toml --mode dryrun-fake --since-hours 1440 --result -
```

## Rollout order

Move to the next step only when the previous one works.

| Step | Command | What it proves |
| --- | --- | --- |
| 0 | `python3 tests/test_pipeline.py` | The logic works (no external services) |
| 1 | `tools/live_check.py --mode dryrun-fake` | Mattermost can be read and decks can be exported; nothing is posted |
| 2 | `tools/live_check.py --mode dryrun-real` | Real summaries, kept on the machine for a human to read |
| 3 | `tools/live_check.py --mode test-channel` | The full flow, posting to the test channel only |
| 4 | Set `reply_mode = "thread"` after a two-week trial | Go live |

## Schedule

```cron
CRON_TZ=Asia/Taipei
30 8 * * 3  cd /opt/lab-summarizer && /usr/bin/python3 main.py --config /path/to/config.toml >> /var/log/lab-summarizer.log 2>&1
```

## Behavior

- **Scan window**: top-level posts from last Wednesday 12:00 until the run.
- **Counts as a deck**: Google Slides links (including ones hidden inside Markdown links) and PDF or PPTX attachments.
- **Skipped**: announcements, previews of next week's topic, posts with only GitHub or spreadsheet links, video attachments, system messages, the bot's own posts, and posts containing `#no-summary`.
- **Dedupe**: by post id. The same deck posted again the next week is summarized again.
- **Deck not shared**: one line in the thread asks the speaker to enable link sharing; the post is not processed again.
- **Model failure**: nothing is posted in the channel; the maintainer gets a direct message.
- **Run report**: after every run that did something, the maintainer gets a direct message with counts and failure codes.
- **Logs**: post ids, status codes, character counts and timings only. Never slide content.

## Not yet verified in the real environment

1. Mattermost reads, uploads and posting (tested against a fake server only).
2. Google Slides export without login (`/export/pdf`) for native decks and uploaded .pptx files.
3. Summary quality and timing on real decks (the Claude CLI path has only been run on synthetic English decks).
4. The Ollama fallback (off by default).

## Known limits

- HTML attachments are off by default. Turning them on runs the attachment's JavaScript in a headless browser; assess the risk first.
- For decks over 32 pages Claude sees a sample of 32 (the first two and last two pages are always kept).
- Claude's login credentials live in the same account as its Read tool. Output is scanned for credential patterns, which will not stop a deliberately encoded leak, so keep other secrets out of that account.

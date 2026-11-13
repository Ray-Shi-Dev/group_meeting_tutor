# One-time setup

For whoever runs the machine that holds the Mattermost token. After this, both Claudes can trigger live checks and read the results on their own, and the token never leaves the machine.

## What only a human can do

Everything else below is scripted. These are the parts no script can do for you:

1. Make the GitHub repo private (Settings → General → Danger Zone → Change visibility).
2. Paste the channel URL and your personal access token into `tools/mm_setup.py` (the token is typed hidden).
3. Only if your Mattermost server restricts bot creation to admins: send the generated request to the admin and save the bot token they give you.
4. Sign in to the Claude CLI once.
5. Register the self-hosted runner (GitHub gives you a one-time registration command).

## Ground rules

- **Keep the repo private.** A self-hosted runner executes code from the repo on your machine; GitHub advises against using one with a public repo.
- **Use a dedicated bot token for anything that posts.** Anyone with write access to the repo can run code on the runner and could therefore reach the token, so keep its reach small: the bot only joins the group meeting channel and the test channel.
- **Never paste a token into a chat, an issue or a file in the repo.** If one leaks, revoke it and issue a new one.

## Steps

### 1. Install tools and get the code

```bash
sudo apt update
sudo apt install -y git poppler-utils python3-tomli
git clone https://github.com/Ray-Shi-Dev/group_meeting_tutor.git && cd group_meeting_tutor
```

`python3 --version` must be 3.10 or newer. Add `libreoffice-impress` if you want PPTX attachments supported.

### 2. Run the Mattermost setup script

Have two things ready:

- The URL of the group meeting channel: open the channel in a browser and copy the address bar. It looks like `https://<server>/<team>/channels/<channel>`.
- A personal access token: Mattermost → Profile → Security → Personal Access Tokens.

```bash
python3 tools/mm_setup.py
```

The script then, using your token:

| Step | Automatic? |
| --- | --- |
| Find the team and the channel | Yes |
| Create a private test channel `slide-summary-test` | Yes |
| Create the bot `slide-summary-bot` | Yes, if the server lets regular users create bots |
| Add the bot to the team, the channel and the test channel | Yes |
| Create the bot's token and save it to a chmod 600 file | Yes, if you created the bot |
| Write `~/.config/lab-summarizer/config.toml` | Yes |

It posts nothing and prints no token. It is safe to run again; each step checks what already exists.

**If the server only lets admins create bots**, the script stops at that step and writes `~/.config/lab-summarizer/admin_request.txt`, a ready-to-send message for the admin. Send it. When the admin gives you the bot token:

```bash
nano ~/.config/lab-summarizer/mm_token      # paste the token, save
chmod 600 ~/.config/lab-summarizer/mm_token
python3 tools/mm_setup.py --force           # adds the bot to the channels and switches the config to the bot token
```

Until then the config uses your personal token, which is enough for the read-only dry runs in step 4. One side effect: the agent skips posts written by the token's owner, so your own posts will not appear.

### 3. Install and sign in to the Claude CLI

Install Claude Code following the official instructions and run `claude` once to sign in.

### 4. Check that it works

```bash
python3 tools/live_check.py --config ~/.config/lab-summarizer/config.toml --mode dryrun-fake --since-hours 1440 --result -
```

This reads the last 60 days of the channel, exports the decks and renders them, and posts nothing. The report it prints contains no secrets or slide content, so you can paste it straight to Claude.

### 5. Register the self-hosted runner (optional, removes the copy-paste)

In the repo: Settings → Actions → Runners → New self-hosted runner → Linux. Run the commands shown there. During `./config.sh`:

- When asked for labels, enter `lab-summarizer` (the workflow finds the machine by this label).
- Press Enter for everything else.

Keep it running:

```bash
sudo ./svc.sh install && sudo ./svc.sh start
```

On WSL without systemd, run `./run.sh` inside tmux instead. While the machine is off or asleep the runner is offline and requests wait in the queue.

Then tell Claude the runner is ready, or bump `request` in `.ci/live-request` and push. A few minutes later `results/live.md` appears on the `ci-results` branch.

## How the live check works

1. Someone changes `.ci/live-request` and pushes to `main`.
2. The runner executes `tools/live_check.py`, which runs `main.py` with the local config and token.
3. A content-free report is written to `results/live.md` on the `ci-results` branch.
4. The summaries themselves stay on the machine in `~/.config/lab-summarizer/last_dryrun/`, or go to the test channel.

The report holds environment checks, status codes, post ids, page counts, character counts and timings. The token, URLs, channel ids, slides and summaries are never uploaded.

| Mode | Posts? | Calls the model? | Use |
| --- | --- | --- | --- |
| `dryrun-fake` | No | No | Confirms the channel can be read and decks can be exported |
| `dryrun-real` | No | Yes | Produces real summaries, kept locally for a human to read |
| `test-channel` | Test channel only | Yes | The full flow; `reply_mode` is ignored, so it cannot post to the real channel |

## Removing the runner

```bash
sudo ./svc.sh stop && sudo ./svc.sh uninstall
./config.sh remove
```

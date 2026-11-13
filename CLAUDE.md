# Instructions for Claude working in this repo

Two people develop this project, each with their own Claude. The three files in `docs/` are the single source of truth that keeps both sides aligned. Follow the rules below.

## Language

- Everything in this repo is written in English: docs, comments, docstrings, CLI help, log messages, CI reports, commit messages, issues and pull requests.
- The exception is text that Chinese-speaking lab members read or that is sent to the model: the prompt templates, validation feedback sent back to the model, and everything posted to Mattermost stay in Traditional Chinese (requirement R17). Do not translate those.

## Before you start working

1. Run `git pull` to get the other side's latest work.
2. Read `docs/STATUS.md`: who is doing what, and what is unclaimed.
3. Read `docs/REQUIREMENTS.md`: the only source of requirements. If the user asks for something that conflicts with it, point out the conflict and ask; do not change requirements on your own.
4. Before changing a design trade-off, check `docs/DECISIONS.md` so you do not undo a settled decision.

## Before you finish working

1. Update `docs/STATUS.md`: change the status of what you touched and add a line at the top of the progress log (date, who, what).
2. Add an entry to `docs/DECISIONS.md` for any new design decision.
3. If a requirement changed, edit `docs/REQUIREMENTS.md` and note the date and reason on that row.
4. Commit and push. Name the requirement or task id in the commit message, for example `T4: fix pptx export`.

## Dividing the work

- Before starting a task, put your owner name on it in `docs/STATUS.md` and push, then write code. This keeps both sides from doing the same thing.
- Do not change a task someone else has in progress. If you need to, leave a note under "To discuss" in STATUS.
- One commit does one thing, so the other Claude can read the diff.

## Never do these

- Never commit `config.toml`, a Mattermost token, channel ids, the lab's URLs, the SQLite state file or `dryrun_out/`. `.gitignore` excludes them; do not work around it.
- Never write slide content, channel conversations, real Google Slides ids, or lab members' names or accounts into any file, commit message or issue. Test fixtures must be synthetic.
- Never post to the real channel without the user's explicit consent. Test with `--dry-run` or `reply_mode = "test_channel"` only.
- Never ask the user to paste a token into the conversation, and never write code that prints a token or the contents of the config file.

## Automated checks

Every push to `main` runs the tests automatically and writes the result to the `ci-results` branch. Read the result yourself after pushing; do not wait for the user to report it:

```bash
git fetch origin ci-results && git show FETCH_HEAD:results/offline.md
git fetch origin ci-results && git show FETCH_HEAD:results/live.md
```

- `results/offline.md`: end-to-end tests on GitHub-hosted machines (Python 3.10, 3.11, 3.13). Updated a minute or two after a push; check that the commit id matches yours.
- `results/live.md`: the live check on the self-hosted runner. To trigger it, edit `.ci/live-request` (pick a mode, bump `request`) and push to `main`.
- Until the self-hosted runner is installed, do not push changes to `.ci/live-request`; the job would only sit in the queue. See T12 in `docs/STATUS.md`.
- The `test-channel` mode really posts to the test channel. Get the user's consent first.
- The results branch is visible to every collaborator. `tools/live_check.py` only passes through whitelisted event codes. When you add a log event, keep URLs, channel ids, account names and slide content out of it.

## Project at a glance

- Entry point: `main.py`. The recommended test order is in `README.md`.
- After changing code, run `python3 tests/test_pipeline.py` and `python3 tests/test_mm_setup.py`. Both must print `ALL PASS` before you push.
- Python 3.10+, standard library only at run time (3.10 also needs python3-tomli). The only external tool is poppler-utils.

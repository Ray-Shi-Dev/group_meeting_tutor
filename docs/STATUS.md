# Status board

Before starting a task, put your owner name on it and push. When done, update the status and add a line to the progress log at the bottom.

Owner is `Ray`, `Collaborator` (replace with your name or handle), or blank for unclaimed.

## Current phase

**Phase 1: run once against the real channel without posting.**

The next milestone is a first batch of summaries from real decks, read by people to judge the quality.

## Waiting on a human

These cannot be scripted. Details are in `docs/SETUP.md`.

| What | Who | State |
| --- | --- | --- |
| Make the GitHub repo private | Ray | Open |
| Run `tools/mm_setup.py` (paste channel URL and personal token) | Ray | Open |
| If the server restricts bot creation: send the generated request to the Mattermost admin | Ray | Open |
| Sign in to the Claude CLI on the execution machine | Ray | Open |
| Register the self-hosted runner | Ray | Open |

## Tasks

| Id | Task | Owner | Status |
| --- | --- | --- | --- |
| T1 | Run `tests/test_pipeline.py` locally and see `ALL PASS` | Ray | Passed in the cloud environment and on GitHub-hosted CI; not yet run on Ray's WSL |
| T2 | Run the `dryrun-fake` live check with a personal token: confirm posts can be read and Google export works (R5, R6) | Ray | Not started (needs `mm_setup.py` to be run) |
| T3 | Confirm the Claude CLI flags `--allowedTools`, `--tools ""`, `--output-format json` behave as the code assumes (R31) | Ray | Done: verified with CLI 2.1.323; `live_check.py` re-checks on the execution machine |
| T4 | Run `dryrun-real`, measure time per deck, tune `vision_timeout_sec` | Ray | Partly done: synthetic decks take about 50 s for 8 pages and 70 s for 30 pages, so 420 s is enough; real decks still to be measured |
| T5 | Have 1–2 people from outside the field read 3 summaries (paper, tool, experience) against the acceptance checklist | | Not started |
| T6 | Bot account and test channel (R26, R30) | Ray | Scripted in T15; waiting on a human to run it |
| T7 | Decide which machine runs the agent and create a dedicated low-privilege account (R36) | | Not started |
| T8 | Deploy cron and run a two-week trial in the test channel (R1, R30) | | Not started |
| T9 | Confirm the `ollama_model` name and decide whether to enable the local fallback (R32) | | Not started |
| T10 | Decide whether to enable HTML attachments (R9) | | Not started |
| T11 | Switch to `reply_mode = "thread"` and go live | | Not started |
| T12 | Automated development loop: offline tests on GitHub-hosted machines plus live checks on a self-hosted runner, results on the `ci-results` branch | Ray | Code done and the offline half is running; the live half waits on the runner |
| T13 | Support Python 3.10 (Ubuntu 22.04 default) | Ray | Done (kept verified by offline-tests) |
| T14 | Convert the repo to English; prompts and Mattermost text stay in Traditional Chinese | Ray | Done |
| T15 | `tools/mm_setup.py`: create the test channel, try to create the bot, save its token, write the config | Ray | Done, tested against a fake server; unverified on the real server |

## To discuss

Questions that need both people or the professor. Move the outcome to `DECISIONS.md`.

- Whose subscription runs the summaries, and do its terms allow scheduled, unattended use?
- Should `#no-summary` be announced to everyone before going live?
- The 08:30 version is often not final. Trigger later, or post a second version after the meeting?

## Done

| Item | Date |
| --- | --- |
| Requirements interview and first spec | 2026-11-12 |
| Summary prompts and harness (three review rounds) | 2026-11-12 |
| Full pipeline: fetch, export, render, post, dedupe, report | 2026-11-12 |
| End-to-end tests (fake Mattermost and fake model) | 2026-11-12 |
| Repo and collaboration docs | 2026-11-13 |
| Offline CI on Python 3.10, 3.11, 3.13 with results on `ci-results` | 2026-11-13 |
| Real Claude CLI run on synthetic decks; prompt tuned from the results | 2026-11-13 |

## Progress log

Newest first. Format: `date | who | what`.

- 2026-11-13 | Ray | T15: added `tools/mm_setup.py` and its tests; `docs/SETUP.md` replaces the runner guide and lists the human-only steps.
- 2026-11-13 | Ray | T14: converted docs, comments, CLI text and CI reports to English (D19). Replaced test fixtures with synthetic ids and rewrote history to remove the old ones (D21).
- 2026-11-13 | Ray | T12: live-check now has a gate job, so `request=0` sends nothing to the self-hosted runner.
- 2026-11-13 | Ray | T12: added the offline-tests and live-check workflows and `tools/live_check.py`.
- 2026-11-13 | Ray | T3, T4: ran the real Claude CLI on synthetic decks end to end; tuned the prompt from the results (D17, D18).
- 2026-11-13 | Ray | T13: Python 3.10 support; per-deck timing log, `--require-test-channel`, Mattermost error code.
- 2026-11-13 | Ray | T1: ran `tests/test_pipeline.py` from the repo head in the cloud environment; all checks passed.
- 2026-11-13 | Ray | Created the repo with requirements, status and decisions docs and CLAUDE.md.
- 2026-11-12 | Ray | First version of the code; end-to-end tests pass against a fake server; real environment unverified.

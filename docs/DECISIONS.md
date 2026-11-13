# Decision log

Design trade-offs that are settled. To overturn one, add a new entry that says which one it replaces; do not edit or delete old entries.

| Id | Date | Decision | Why |
| --- | --- | --- | --- |
| D1 | 2026-11-12 | Summaries use the subscription Claude CLI, not a pay-per-call API | Only 1–4 decks a week; the goal is zero API cost |
| D2 | 2026-11-12 | Code fetches, validates, formats and appends the footer; the model only writes the summary | Predictable and testable; a model mistake has a small blast radius |
| D3 | 2026-11-12 | The local-model fallback is off by default; if Claude fails, skip and message the maintainer | Small models are clearly worse; during the trial, no post beats a bad post |
| D4 | 2026-11-12 | HTML attachments are off by default | Converting them runs the attachment's JavaScript in a headless browser |
| D5 | 2026-11-12 | Dedupe by post id, not deck id | Speakers who are postponed post the same link again the next week |
| D6 | 2026-11-12 | Hard upper limit of 400 characters, no hard lower limit | On a retry the model no longer sees the slides; asking for more text only produces padding or invention |
| D7 | 2026-11-12 | Over-length output is fixed by sending the previous JSON back as text, without re-reading images | Much faster, and it does not drift |
| D8 | 2026-11-12 | If a retry fails midway, use the schema-valid candidate in hand instead of switching to the fallback | A slightly long Claude summary still beats the fallback model |
| D9 | 2026-11-12 | Isolation uses a dedicated low-privilege account, not bubblewrap | bubblewrap easily breaks CLI startup, and the failure is not obvious |
| D10 | 2026-11-12 | If output looks like a leaked credential, post nothing for that post and let the maintainer check | It suggests the deck carries hidden instructions; do not retry automatically |
| D11 | 2026-11-12 | Posting defaults to the test channel; replying in real threads needs a manual config change | Prevents accidental posts to the real channel during testing |
| D12 | 2026-11-12 | Claude sees at most 32 pages; longer decks are sampled, always keeping the first two and last two pages | Most decks are 20–40 pages and fit whole; conclusions are usually at the end |
| D13 | 2026-11-13 | Requirements, status and decisions live in `docs/`, and `CLAUDE.md` requires reading and updating them around every session | Two people develop with separate Claudes and need one shared source of truth |
| D14 | 2026-11-13 | The token exists only on the execution machine; Claude pushes code through GitHub and reads results from the `ci-results` branch, never handling the token | Development can loop on its own while the token stays out of chats and out of the repo |
| D15 | 2026-11-13 | Results sent back contain only whitelisted event codes, post ids, page counts, character counts and timings; summaries stay on the machine or go to the test channel | Slide content must never enter version control |
| D16 | 2026-11-13 | Live checks are triggered only by pushes to `main` or manual runs, never by pull requests, and always pass `--require-test-channel` | Limits who can run code on the machine that holds the token, and prevents posts to the real channel |
| D17 | 2026-11-13 | The prompt's length target is 300–360 (the limit stays 400) | Measured: aiming at 400 produced 404–446 characters and one or two extra retries; with the lower target it passes first time |
| D18 | 2026-11-13 | An isolated TBD, or the phrase "slides still being adjusted" in the post, does not make a deck unfinished | Measured: one TBD line flagged a whole deck, and nearly every post says the slides are still being adjusted |
| D19 | 2026-11-13 | Everything in the repo is in English; prompts, feedback sent to the model and text posted to Mattermost stay in Traditional Chinese | Owner's preference for GitHub content; the Chinese parts are product requirements (R17) |
| D20 | 2026-11-13 | Mattermost setup is scripted in `tools/mm_setup.py` using the developer's personal token; the bot token is written straight to a chmod 600 file | Leaves a human only the steps the server forbids to script, and no token is ever displayed or pasted into a chat |
| D21 | 2026-11-13 | Test fixtures use synthetic ids and messages only | Early fixtures reused deck ids seen in the real channel; they were replaced and removed from history |

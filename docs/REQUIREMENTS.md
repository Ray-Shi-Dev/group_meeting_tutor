# Requirements

This file is the only source of requirements. To change one, edit it here and note the date and reason on that row.

**Goal in one sentence**: before each Wednesday group meeting, automatically reply under every slide post in the channel with an illustrated summary that someone outside the field can follow, with no human step.

Status values:

- **Done**: implemented and passing the tests against fake servers.
- **Unverified**: implemented, not yet checked in the real environment.
- **Not started**

## Trigger and scope

| Id | Requirement | Status |
| --- | --- | --- |
| R1 | Run once every Wednesday at 08:30 (Asia/Taipei), using the deck as it is at that moment | Done (schedule not deployed) |
| R2 | Scan top-level posts in the group meeting channel from last Wednesday 12:00 until the run; thread replies are ignored | Done |
| R3 | The whole batch finishes within 30 minutes, before the 09:10 meeting | Done |
| R4 | Fully automatic: no human confirmation once live | Done |

## Slide sources

| Id | Requirement | Status |
| --- | --- | --- |
| R5 | Google Slides links, exported to PDF without logging in | Unverified |
| R6 | .pptx files uploaded to Drive (URL carries `rtpof=true`) | Unverified |
| R7 | URLs hidden inside Markdown link text are found too | Done |
| R8 | Post attachments: PDF, PPTX | Done |
| R9 | Post attachments: HTML decks | Done, off by default (D4) |
| R10 | Several decks in one post are merged into one reply | Done |

## Posts to skip

| Id | Requirement | Status |
| --- | --- | --- |
| R11 | Posts with no deck link and no deck attachment: announcements, previews of next week's topic, requests for feedback | Done |
| R12 | Posts whose only links are GitHub, wiki, social media, spreadsheets and other non-deck pages | Done |
| R13 | Video attachments, system messages, the bot's own posts | Done |
| R14 | Posts containing `#no-summary` (for speakers who opt out) | Done |
| R15 | Dedupe by post id: never reply twice to one post; the same deck posted again the next week is summarized again | Done |

## Summary content

| Id | Requirement | Status |
| --- | --- | --- |
| R16 | Reader: a bright student with no background in the topic, done reading in one minute | Done (quality unverified) |
| R17 | Traditional Chinese as used in Taiwan; technical terms keep their English name plus a plain-language gloss | Done (quality unverified) |
| R18 | Target 300–400 characters, hard limit 400; shorter is fine for thin decks, padding is not | Done (the prompt aims at 300–360 to leave headroom, D17) |
| R19 | Fixed fields: one-line gist, why it matters, what you take away (2–3), key methods and findings (3–5), glossary (0–4), questions for the speaker (2) | Done |
| R20 | 2–3 key slide images, chosen only from pages the model actually saw, never the cover or outline | Done |
| R21 | Grounded in the deck only; what the deck does not say is reported as "not stated", never guessed | Done (quality unverified) |
| R22 | A clearly unfinished deck is flagged at the top of the reply | Done (D18) |
| R23 | The point is resonance and takeaways for the audience, not a table of contents | Done (quality unverified) |
| R24 | Works for three kinds of talk: paper reading, tool walkthrough, experience sharing; analogies only when they help | Done (quality unverified) |
| R25 | Every reply ends with a fixed note: AI-generated from the 08:30 version; the speaker's talk is authoritative | Done |

## Publishing and failures

| Id | Requirement | Status |
| --- | --- | --- |
| R26 | A bot account replies in the thread of the original post, one reply per post | Done (bot account not created yet) |
| R27 | If the deck is not shared, reply with one line asking the speaker to enable link sharing; no summary | Done |
| R28 | On model or system failure, post nothing in the channel; send the maintainer a direct message | Done |
| R29 | After each run, send the maintainer a direct message with counts of successes, failures and unshared decks, with reason codes | Done |
| R30 | Rollout: dry-run → two-week trial in a test channel → replies in the real threads | In progress |

## Cost

| Id | Requirement | Status |
| --- | --- | --- |
| R31 | No pay-per-call API; summaries use the Claude CLI in non-interactive mode on an existing subscription | Done: verified with CLI 2.1.323 on synthetic decks; unverified on the lab host |
| R32 | Optional local-model fallback (Ollama) sharing the same prompts and validation | Unverified, off by default (D3) |

## Security

| Id | Requirement | Status |
| --- | --- | --- |
| R33 | Logs hold post ids, status codes, character counts and timings only; never slide content | Done |
| R34 | The token is never in version control or in the config file; the token file must be chmod 600 | Done |
| R35 | Text inside slides and posts is data, never instructions to the model | Done |
| R36 | The model runs in a low-privilege account or container that cannot read secrets such as the Mattermost token | Done (deployment not done) |
| R37 | If output looks like a leaked credential, drop that post and notify the maintainer; no retry | Done |

## Out of scope

- Decks posted or changed after 08:30.
- Answering follow-up questions in the thread.
- Weekly digests or long-term archiving.

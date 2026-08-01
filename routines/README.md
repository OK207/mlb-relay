# Routine prompts

The `.txt` files here are the stored prompts for the scheduled Claude routines.
They are kept in git so a delivery break is diffable instead of guesswork.

| File | Routine | Schedule (UTC) |
|---|---|---|
| `mlb-daily-11am.txt` | MLB Daily Picks - 11:00 AM ET | `0 15 * * *` |
| `mlb-afternoon-515pm.txt` | MLB Afternoon Props + Evening ML | `15 21 * * *` |
| `nba-daily-1015am.txt` | NBA Daily Picks - 10:15 AM ET | `15 14 * * *` |
| `ufc-weekly-sat.txt` | UFC Weekly Fight Card | `0 18 * * 6` |

Editing a file here does **not** change the live routine. The routines were
created through the web UI, so the prompt has to be pasted into the routine's
settings by hand. Keep the two in sync.

## How delivery works

Everything is driven by one `git push` to `main`:

```
routine session
  writes picks/<date>.json, grades/<date>.json, dispatch/<date>.txt
  git push origin main
        |
        +--> .github/workflows/relay.yml   (on push to dispatch/*.txt)
        |      -> Telegram sendMessage
        |
        +--> .github/workflows/sheets.yml  (on push to picks/**.json, grades/**.json)
               -> Google Sheets (MLB tab = sheet1, NBA tab)
```

No API token is involved anywhere. The clone's `origin` remote is already
authenticated by the execution environment.

## Why the REST API is not used any more

Delivery broke twice, both times because the execution proxy tightened what a
routine session may send to `api.github.com`:

- **After ~2026-06-22** — `POST /repos/:owner/:repo/dispatches` started
  returning `403 repository_dispatch is not permitted for this session type`.
  This killed the `repository_dispatch` path both workflows originally used.
  A `push:` trigger was added to `relay.yml` on 2026-07-17 as a workaround.
- **After 2026-07-19** — `PUT /repos/:owner/:repo/contents/:path` started
  returning `403 Write access to this GitHub API path is not permitted through
  this proxy`. That killed the remaining path, so no commit landed, so the
  `push:` trigger never fired and texts stopped entirely.

Both 403s are returned by the proxy **before the request reaches GitHub**, so
they happen no matter what credential is presented — a valid token, an expired
token, or a string of nonsense all get the same response. Any diagnosis that
blames an expired or revoked token here is wrong.

To confirm the blocks are still in place:

```sh
# both return 403 from the proxy, with an explanatory JSON body
curl -s -X POST -H "Authorization: Bearer anything" \
  -d '{"event_type":"probe"}' \
  https://api.github.com/repos/OK207/mlb-relay/dispatches

curl -s -X PUT -H "Authorization: Bearer anything" \
  -d '{"message":"probe"}' \
  https://api.github.com/repos/OK207/mlb-relay/contents/probe.json
```

Reads (`GET`) still work, but the routines no longer depend on them — they read
from the local clone instead.

## Debugging a missed text

1. Did a commit land on `main` for that date? `git log --oneline -5 origin/main`
   - No commit -> the routine failed before the push. Check the routine's run
     transcript for the `git push` output.
2. Did the relay workflow run? Actions tab -> "MLB Relay".
   - The job now **fails loudly** if Telegram rejects the message. It used to
     pipe `curl` output to nowhere, so a rejected send looked like success.
3. Did the sheets workflow run? Actions tab -> "Update Google Sheet".

## Workflow behaviour worth knowing

- A push is diffed over `github.event.before..after`, so several commits in one
  push are all processed. The old code diffed `HEAD~1..HEAD` and silently
  ignored everything but the tip commit.
- `sheets.yml` handles **every** matching file in the push. The old code
  `break`-ed on the first match, so a commit carrying both yesterday's grades
  and today's picks only ever applied one of them.
- `relay.yml` chunks messages at 3900 chars (Telegram's limit is 4096).
- UFC picks live under `picks/ufc/` and are deliberately not mirrored to
  Google Sheets; `sheets.yml` only matches `picks/<date>.json` and
  `picks/nba/<date>.json`.

## Backfill status (as of 2026-08-01)

Delivery was broken from 6/18 onward, so picks stopped being recorded. What has
been recovered so far, from the routines' own 11am session transcripts:

- **Recorded in git and logged to the sheet in date order:** 7/1–7/11, 7/16,
  7/18, 7/20–8/1 (51 bets). Every odds/units pair was cross-checked against the
  projected return the routine printed at the time before being written.
- **Still missing** (no transcript supplied yet): 6/10, 6/18–6/30, 7/12–7/15
  — 18 days. Those cards exist only in the run sessions at
  [claude.ai/code/routines](https://claude.ai/code/routines).
- **7/17** is a known conflict: the 11am transcript lists Yankees +105 2u,
  Cardinals -112 1u, Red Sox -130 1u, while the repo file (pushed 1:43pm, and
  already graded) has Red Sox -130 2u and Yankees +100 1u. The repo version
  stands; the transcript version was not applied.
- **51 backfilled bets are logged but ungraded** (column E empty). Grading
  needs a verified final score per bet.

Do **not** regenerate missing picks by re-running the model. Those games have
already been played, so anything produced now is chosen with hindsight and
would turn the tracked record into fiction. Only transcribe what the routine
actually published at the time.

## Reconciling the sheet

`reconcile.yml` (Actions tab -> Reconcile Sheet -> Run workflow):

- `mode: inspect` — read-only. Reports sheet shape, date range, out-of-order
  rows, and which repo picks are missing from the sheet. Run this first.
- `mode: apply` + `confirm: yes` — merges missing repo picks into their correct
  date position and rebuilds the F/G/H running-total chain. Preserves columns
  A–E and I–K per row; refuses to run if any row has a date but no bet.

Commit with `[skip-sheets]` in the message to land picks in git without the
sheets workflow appending them to the bottom, then place them with `apply`.

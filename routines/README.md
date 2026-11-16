# Routine prompts

The `.txt` files here are the stored prompts for the scheduled Claude routines.
They are kept in git so a change is diffable instead of guesswork.

| File | Routine | Schedule (UTC) |
|---|---|---|
| `mlb-daily-11am.txt` | MLB Daily Picks - 11:00 AM ET | `0 15 * * *` |
| `mlb-afternoon-515pm.txt` | Afternoon: line check (all sports) + MLB evening games | `15 21 * * *` |
| `nba-daily-1015am.txt` | NBA Daily Picks - 10:15 AM ET | `15 14 * * *` |
| `ufc-weekly-sat.txt` | UFC Weekly Fight Card | see "UFC timing" below |
| `cbb-daily-1030am.txt` | CBB Daily Picks (not scheduled yet) | suggested `30 15 * * *` |

**The files here on `main` are the instructions.** Each routine's stored
prompt should be nothing more than a pointer to its file, e.g.

> Run `cd /home/user/mlb-relay && git checkout -q main && git fetch -q origin main && git reset -q --hard origin/main`, then read `routines/nba-daily-1015am.txt` in full and follow it exactly.

so a prompt never has to be pasted again: edit the file, merge to `main`,
and the next run uses it. The routines were created in the web UI, which
means only their owner can change the stored prompt or the schedule
(claude.ai/code/routines); sessions cannot. Until a routine's stored prompt
is replaced with its pointer, the repo's `CLAUDE.md` tells a routine that
arrives with an old prompt to follow the file instead.

## What was wrong, and what changed (2026-11-16)

### 1. The routines could not reach any data

The routines run in the "Default" cloud environment. Its network allowlist was
empty, so every scripted request the prompts made was refused by the proxy:
The Odds API (the key had **0 of 500 credits used**), ESPN and MLB scores,
Baseball Savant, Polymarket, and the direct Telegram send. Each card was built
from web-search snippets instead: approximate, sometimes stale prices, games
"not found", "no current odds", and every text taking the relay fallback.

The environment now allows `api.the-odds-api.com`, `api.telegram.org`,
`statsapi.mlb.com`, `baseballsavant.mlb.com`, `site.api.espn.com`,
`site.web.api.espn.com`, `gamma-api.polymarket.com`, `api.open-meteo.com`,
`geocoding-api.open-meteo.com`, `www.rotowire.com`, `www.covers.com`,
`ufcstats.com`, `www.ufcstats.com` and `barttorvik.com`. A new data source
needs its host added there (cloud environment menu -> Edit -> Allowed domains).

### 2. The method manufactured edges

Graded record, 5/12 - 11/15 (every bet graded from official scores):

| Segment | Bets | Record | Units | ROI |
|---|---|---|---|---|
| MLB, all | 172 | 91-78-3 | -1.11 | -0.5% |
| MLB favorites -120 to -249 | 112 | 71-40-1 | +15.95 | +10.9% |
| MLB underdogs / even money | 43 | 12-29-2 | -14.33 | -34.3% |
| NBA, all | 42 | 17-25 | -10.84 | -27.4% |
| NBA 1.5u "high confidence" | 9 | 1-8 | -11.12 | -82.4% |
| NBA spreads | 9 | 1-8 | -6.55 | -77.1% |
| UFC (Gaethje corrected to +3.75) | 17 | 6-10-1 | +0.47 | +4.1% |

Across all 231 bets the picks won about as often as their prices implied -
no edge, minus the vig. The NBA prompt is the clearest case: it built a win
probability from team ratings, weighted it 65% (Polymarket was never
reachable), and called the gap to the book an edge. The bigger the gap the
bigger the stake, so its largest bets were its largest errors.

Every sport now works the same way:

- **The market is the starting point.** `scripts/sheet.py` takes every US
  book's price, removes the vig, and prints the median as the fair
  probability, beside the best price at the books in `config/betting.json`.
- **The analyst may move that fair line only for a named, checkable reason**
  (a star ruled out after the line was set, a scratched starter, a taxed
  bullpen ...), by a bounded amount: at most 4 points NBA/CBB, 5 MLB/UFC.
  "The better team" is not a reason.
- **`scripts/card.py` decides, not the prompt.** It takes the price, book,
  fair line, edge and stake from the saved sheet and rejects anything outside
  the rules: a game not on the slate, a price nobody offers, a shift past the
  limit, an edge under the minimum, too many bets. A pick can no longer go
  out on a team that is not playing or at a price read off a search page.
- **Edges are measured against the price actually bet**, vig included.
- **No quotas.** "No bets today" is the usual card.
- **MLB:** favorites only (-105 to -200). **NBA:** moneylines only, -250 to
  +200, no 1.5u tier. **UFC:** -300 to +250, at most 2 a card, no "underdogs
  are +EV". **CBB:** spreads up to 12.5 and moneylines, teams with 5+ games.

This will produce far fewer bets. That is the fix, not a side effect: the old
volume was the cost.

### 3. Nothing measured whether the picks were any good

Win-loss needs hundreds of bets to say anything. The 5:15 PM session now runs
`scripts/clv.py`: for each pick made that day it re-reads the market and
records how far the fair line has moved toward or away from the pick
(`clv/<sport>/<date>.json`). Each text ends with the record since
`rules_from` and the average line value. Positive line value over a few
dozen bets is the earliest honest sign of an edge; negative means stop.

### 4. Bookkeeping

- Grading is done by `scripts/grade.py` from ESPN's final scores (MLB
  strikeout props from MLB boxscores). Five old bets that were never graded
  are now settled (7/19 A's L, 8/1 Yankees L and Dodgers L, 8/20 Rays L,
  11/15 Pacers +6.5 L, 11/14 Harrison W).
- Gaethje +500 at 0.75u was recorded as +4.50 (stake included); it is +3.75.
  **The UFC tab in the Sheet still shows +4.5 in that row** - change it by hand.
- Dates, file names, payouts and the Telegram send are all computed by
  scripts; nothing in a prompt types a date.
- `data.yml` (GitHub started its schedule 5-10 hours late every day, so the
  bundle reached the 11 AM card zero times) is no longer used by the
  routines: they fetch the same data themselves. On a day with no games it
  now writes nothing instead of committing an empty bundle.
- The site reads cards from `messages/` as well as `dispatch/`, and has a CBB tab.
- `grades/2026-08-31.json` (Braves ML, L) has no matching picks file: the
  pick was texted but never logged. It is in the Sheet, not in the totals above.

## Two workflow files to paste by hand

Sessions like the one that made these changes are not allowed to push to
`.github/workflows/`. Two updated workflows are in `routines/workflows/`;
on GitHub open the live file -> Edit -> replace everything -> Commit.

- `routines/workflows/sheets.yml` -> `.github/workflows/sheets.yml`. Adds a
  CBB tab. **Needed before the CBB routine is switched on**, otherwise its
  picks are saved and texted but never reach the Sheet.
- `routines/workflows/data.yml` -> `.github/workflows/data.yml`. Removes the
  daily schedule. Optional tidy-up.

## The scripts

| Script | What it does |
|---|---|
| `scripts/sheet.py <sport>` | Slate, prices from every book, fair line, best price, context. Saves `lines/<sport>/<date>.json`. 1 credit (2 for cbb). |
| `scripts/card.py <sport> <file>` | Validates the analyst's candidates against the rules and writes the picks file. |
| `scripts/grade.py <sport\|all>` | Grades ungraded picks from official scores. |
| `scripts/clv.py` | Line check for open picks. 1 credit per sport with open picks. |
| `scripts/publish.py <sport> <file>` | Saves the text, sends to Telegram (relay fallback), commits, pushes. |
| `scripts/fetch_daily_data.py`, `game_sheet.py` | MLB starters, splits, bullpens, weather. |

Odds API use is about 2 credits a day for NBA, 3-4 for CBB, 2 for MLB in
season and 2 a week for UFC: roughly 200-250 of the 500 free credits a month
with everything running.

## The knobs: `config/betting.json`

- `books`: the sportsbooks you can bet at. Picks only quote these. Add
  `betmgm`, `williamhill_us` (Caesars), `espnbet`, `fanatics`, `betrivers`
  if you have them: each extra book improves the best price.
- Per sport: allowed price range, shift limit, stake tiers, daily caps, and
  `stake_scale` (0 = keep sending picks as tracking-only at 0u).
- `rules_from`: the date the record line in each text counts from.

Changing this file on `main` takes effect on the next run; no prompt changes.

## UFC timing

The routine fired Saturdays at 18:00 UTC (1 PM ET in winter). Cards in Europe,
the Gulf and Asia have started by then, so it reached for the following
week's card and priced it seven days out. `sheet.py ufc` only looks three
days ahead and only at bouts that have not started. Run it on **Friday 22:00
UTC** (`0 22 * * 5`): after weigh-ins, before every Saturday card.

## The claude.ai skills

`skills/` holds updated copies of the mlb, nba, ufc and cbb skills used in
claude.ai chats. They carried the same method as the old prompts (own-model
probabilities, pick quotas, "underdogs are often +EV", a stale "32-12, +29.5%
ROI" record). Upload each `SKILL.md` over the existing skill in claude.ai
(Settings -> Capabilities -> Skills). The routines do not load them.

## How delivery works

```
routine session (network open to the hosts listed above)
  scripts/grade.py, sheet.py, card.py     -> picks/, grades/, lines/
  scripts/publish.py
     -> messages/<date><tag>.txt
     -> Telegram sendMessage, directly
        (only if that fails: dispatch/<date><tag>.txt)
     -> git push origin main  (falls back to claude/auto)
           |
           +--> .github/workflows/relay.yml   (on push to dispatch/*.txt)
           |      -> Telegram sendMessage
           +--> .github/workflows/sheets.yml  (on push to picks/**.json, grades/**.json)
                  -> Google Sheets (MLB = sheet1; NBA, UFC, CBB tabs)
```

No GitHub API token is involved anywhere. The clone's `origin` remote is
already authenticated by the execution environment.

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

1. Open the routine's run and read its final response: `publish.py` prints
   `SENT: direct to Telegram` or `SEND_VIA_RELAY: ...` with the reason, then
   `PUSHED: main`.
2. Is the text in `messages/<date><tag>.txt` on `main`? If not, the routine
   stopped before publishing; its transcript shows which script failed.
3. Relay fallback only: Actions tab -> "MLB Relay". The job fails loudly if
   Telegram rejects the message.
4. `PRICES_UNAVAILABLE` or `... is not on this environment's allowed hosts`
   in a text means the environment's network allowlist lost a host (see
   "What was wrong" above).
5. Did the sheets workflow run? Actions tab -> "Update Google Sheet".

## Workflow behaviour worth knowing

- A push is diffed over `github.event.before..after`, so several commits in one
  push are all processed. The old code diffed `HEAD~1..HEAD` and silently
  ignored everything but the tip commit.
- `sheets.yml` handles **every** matching file in the push. The old code
  `break`-ed on the first match, so a commit carrying both yesterday's grades
  and today's picks only ever applied one of them.
- `relay.yml` chunks messages at 3900 chars (Telegram's limit is 4096).
- Each sport has its own worksheet: MLB is `sheet1`, NBA is the `NBA` tab, UFC
  is the `UFC` tab (created automatically on first use). Running totals in
  F/G/H are cumulative per worksheet, so the sports are tracked separately.
- UFC pick files are `{"event":..., "picks":[...]}` rather than a bare list,
  and UFC grades live at `picks/ufc/grades/<date>.json`. Both workflows
  unwrap the former and special-case the latter.

## Backfill status (as of 2026-08-01)

Delivery was broken from 6/18 onward, so picks stopped being recorded. What has
been recovered so far, from the routines' own 11am session transcripts:

- **Recorded in git and logged to the sheet in date order:** 7/1–7/11, 7/16,
  7/18, 7/20–8/1 (51 bets). Every odds/units pair was cross-checked against the
  projected return the routine printed at the time before being written.
- **Afternoon (5pm) session recovered:** 15 evening ML bets across 6/30, 7/7,
  7/9, 7/10, 7/12, 7/16, 7/18, 7/19, 7/25, 7/26, 7/27, 7/31, appended to each
  date's morning card. 12 of the 15 printed a projected return that their odds
  and stake reproduce exactly; the other 3 gave only an edge tier.
- **Accounted for, not missing:** 6/10 and most of 6/18–6/30 are days the model
  did not run, and 7/13–7/15 was the All-Star break. No cards exist for those
  dates.
- **Two dates where the 5pm session ran but the 11am one did not:** 6/30 and
  7/12 have afternoon picks and no morning card, so `picks/2026-06-30.json` and
  `picks/2026-07-12.json` hold the afternoon session alone. Worth noting that
  6/30 falls inside the "model did not work" window and 7/12 was initially
  thought to be All-Star break — the 5pm run evidently produced cards on both
  (7/12's references a Dodgers/Diamondbacks game), so the outage was specific
  to the morning routine and the break started 7/13.
- **7/17** is a known conflict: the 11am transcript lists Yankees +105 2u,
  Cardinals -112 1u, Red Sox -130 1u, while the repo file (pushed 1:43pm, and
  already graded) has Red Sox -130 2u and Yankees +100 1u. The repo version
  stands; the transcript version was not applied.
- **66 backfilled bets are logged but ungraded** (column E empty). Grading
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

## UFC tab — 6/14 resolved

The UFC worksheet already held hand-entered rows for 6/14 named in a different
style to what the routine writes (`Gane ML vs Pereira - UFC Freedom 250` vs
`Gane ML`), and the two sources disagreed on price: the sheet said +105, the
repo said -113.

Resolved in favour of the repo's **-113**:

- the duplicate Gane row the backfill created has been removed
- the surviving row's odds were corrected +105 -> -113
- 6/14 is graded: Gane **W +0.88u**, Garcia **L -0.75u**

Both workflows now compare bets on the leading clause, so the two naming
conventions match for dedupe *and* for grading. `reconcile` also corrects a
row's odds/units when they disagree with the repo, logging every change.

The two hand-entered 6/14 rows, **Gaethje ML vs Topuria +500 0.75u** (W +4.5u)
and **Zahabi ML vs O'Malley +275 0.5u** (L -0.5u), were confirmed as UFC picks
on 2026-10-06 and added to `picks/ufc/2026-06-14.json` and its grades file.
The same day, the hand-graded 7/11, 7/18 and 10/3 results were copied from
the tab into `picks/ufc/grades/`. The repo and the tab now agree: 12 bets,
+0.78u.

**Open (2026-10-22):** the Gaethje result is the total return, not the
profit. 0.75u at +500 wins +3.75u; +4.5u adds the stake back. Both the tab and
`picks/ufc/grades/2026-06-14.json` overstate UFC by 0.75u until corrected.

## Known gaps in the MLB record

- **8/28 Yankees ML -165 1u (W, +0.61u)** and **8/31 Braves ML -163 1u (L,
  -1.00u)** were texted, but the routine wrote them to `picks/TODAY.json`, so
  neither reached the sheet. 8/31's grade exists; neither picks file does.
- **10/4 Rays ML** was removed on 10/6: the Rays had no game that day.
- The bets listed as never graded on 10/22 (7/19 A's, 8/1 Yankees and
  Dodgers, 8/20 Rays) were settled on 11/16 from ESPN's final scores.

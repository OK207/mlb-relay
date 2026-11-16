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

## The record, and the rules it produced (review of 2026-10-22)

Everything the routines published from 5/12 to 10/20, graded: **194 bets,
100-90-4, -0.98u on 228.75u staked.** MLB carries it; NBA and UFC lose.
The hand-entered 4/25-5/11 rows in the MLB tab (about +8u) are not in the repo
and are not counted here.

| Segment | Bets | Record | Units | ROI |
|---|---|---|---|---|
| MLB, all | 168 | 92-73-3 | +5.25 | +2.5% |
| MLB favorites | 125 | 79-45-1 | +18.35 | +11.2% |
| MLB underdogs / even money | 42 | 12-28-2 | -13.58 | -33.1% |
| MLB 2u (HIGH CONFIDENCE) | 47 | 32-15 | +15.87 | +16.9% |
| MLB 1u (VALUE) | 100 | 49-48-3 | -11.20 | -11.2% |
| MLB 1u underdogs alone | 23 | 5-16 | -10.57 | -46.0% |
| MLB 0.5u (LEAN, mostly plus money) | 15 | 7-8 | -0.72 | -9.6% |
| MLB afternoon session | 18 | 11-6-1 | +1.91 | +13.2% |
| NBA | 13 | 5-8 | -5.51 | -40.8% |
| UFC (Gaethje corrected to +3.75) | 13 | 3-9-1 | -0.72 | -7.8% |

Across all 168 MLB bets the picks won 55.8% of decisions against a 55.8%
break-even: as a whole they won exactly as often as the prices said they
would. The profit is all in the favorites, and in the 2u tier. With ~170 bets
the standard error on ROI is about +/-7%, so read the smaller rows as hints,
not facts. Day of week, month and team splits were checked and are noise.

What the prompts now do about it:

- **MLB: favorites only.** The underdog rows above are the whole of the loss.
  The LEAN tier (0.5u plus-money) is gone. 2u HIGH CONFIDENCE stays as is;
  -200 or shorter caps at 1u.
- **Best price, not DraftKings only.** Each pick names the best price among the
  books in `BOOKS`. Five cents better on every MLB bet would have turned +5.25u
  into +8.6u with the same picks.
- **No pick counts to hit.** "Target 2-4 plays" (MLB), "1-3 picks" (NBA) and
  "3-5 plays" (UFC) are gone; zero picks is a normal outcome.
- **Only verified games, only real prices.** On 10/4 a pick went out on the
  Rays, who had no game that day (ALDS games 1 and 2 were 10/3 and 10/5).
- **A sanity check against the market.** A model probability more than 8
  points from the no-vig market line is treated as a data error first.
- **Line check (CLV).** The 5:15pm session records how each morning pick's
  price has moved (`clv/<date>.json`) and texts it. Beating later prices is
  the earliest reliable sign of a real edge; win-loss takes thousands of bets.
- **NBA:** the old edge was measured against a no-vig price, which overstates
  every edge by about two points. Now measured against the price actually bet.
  No bets until teams have played 10 games (opening night lost 3u at 1.5u
  each). Moneylines only, at most 2 a day, `STAKE_SCALE = 0.5`.
- **UFC:** the built-in belief that "underdogs are often +EV" is gone (they went
  2-7). The model starts at the no-vig market line and moves at most 8 points;
  A-tier only, nothing longer than +250, at most 2 a card, `STAKE_SCALE = 0.5`.
- **Afternoon:** asked statsapi for regular-season games only, so it reported
  "No games today" 15 times in October while playoff games were on. Fixed.
  Its K props needed a confirmed umpire, which never came, so none were
  published from May to October; an unknown umpire is now neutral.

`STAKE_SCALE` at the top of the NBA and UFC prompts is the dial. 0 publishes
tracking-only picks; 1 is full stakes. Expected value says those two sports
should sit at 0 until the line check shows an edge; 0.5 is the compromise.

## The data bundle, and why it never reached the 11am card

`data.yml` was scheduled for 9:00 AM ET. GitHub started it between 12:15 and
5:40 PM ET on every day from 9/22 to 10/22, so the bundle landed after the
11 AM card 27 times out of 27. On top of that, every bundle fell back from
Baseball Savant (the CSV's byte-order mark failed a header check), so xERA,
K% and BB% were never in it, and the multi-book "best" prices mixed run-line
and total juice in with moneylines.

Now the routines ask for the bundle by pushing a line to `requests/data.txt`;
a push starts the workflow within seconds and the bundle lands in 1-3 minutes.
Each game carries the best price per side and its book, the no-vig fair line,
SP handedness, season line and last three starts, bullpen use over three days,
the HP umpire once posted, lineup splits against the SP's hand, and the
forecast for the hour of first pitch. `scripts/game_sheet.py` prints it as one
block per game.

## Setup checklist (2026-10-22 changes)

1. **Merge this branch into `main`.** The routines read `main`.
2. **Paste the two workflow files.** These sessions cannot push to
   `.github/workflows/`, so the new versions are in `routines/workflows/`.
   On GitHub, open `.github/workflows/data.yml` -> Edit -> replace everything
   with `routines/workflows/data.yml`; same for `grade.yml`.
3. **Paste the four prompts** into the routines (Instructions box).
4. **Environment variable `BOOKS`** (claude.ai routine environment): the books
   you have accounts with, as The Odds API names them, e.g.
   `draftkings,fanduel,betmgm,williamhill_us` (Caesars is `williamhill_us`).
   Also add it as a repository **variable** `BOOKS` on GitHub (Settings ->
   Secrets and variables -> Actions -> Variables).
5. **Repository secret `ODDS_API_KEY`** on GitHub (same page, Secrets), with
   the same key the routines already use. Without it the bundle falls back to
   the covers.com scrape and has no per-book prices.
6. **Delete the disabled routine named "test".** Its prompt holds the
   Telegram bot token in plain text.
7. **Optional:** move the NBA, UFC and afternoon routines from Sonnet 4.6 to
   the model the 11 AM card uses or newer (routine settings -> model).

## How delivery works

Everything is driven by one `git push` to `main`:

```
routine session
  pushes requests/data.txt ------------> .github/workflows/data.yml
                                           -> data/<date>.json (1-3 min)
  writes picks/<date>.json, grades/<date>.json, dispatch/<date>.txt
  git push origin main
        |
        +--> .github/workflows/relay.yml   (on push to dispatch/*.txt)
        |      -> Telegram sendMessage
        |
        +--> .github/workflows/sheets.yml  (on push to picks/**.json, grades/**.json)
               -> Google Sheets (MLB tab = sheet1, NBA tab, UFC tab)

nightly: .github/workflows/grade.yml grades MLB picks from MLB's API and
         fills column E; the 11 AM card uses those grades when present.
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
- Each sport has its own worksheet: MLB is `sheet1`, NBA is the `NBA` tab, UFC
  is the `UFC` tab (created automatically on first use). Running totals in
  F/G/H are cumulative per worksheet, so the sports are tracked separately.
- UFC pick files are `{"event":..., "picks":[...]}` rather than a bare list,
  and UFC grades live at `picks/ufc/grades/<date>.json`. Both workflows
  unwrap the former and special-case the latter.

## The Odds API (optional, added 2026-09-30)

MLB, NBA and UFC odds steps now try [The Odds API](https://the-odds-api.com)
before falling back to WebFetch/WebSearch scraping. This is opt-in: if
`ODDS_API_KEY` isn't set in the routine's environment variables, every step
silently skips straight to the existing scrape/WebSearch path — no behavior
change, no error.

**Why:** one call returns DraftKings' (and FanDuel's) odds for the *entire*
day's slate as structured JSON, instead of scraping oddsshark/covers.com or
falling back to WebSearch. Free tier is 500 credits/month, reset on the 1st
of each calendar month; `h2h`/`spreads`/`totals` cost 1 credit per market
(e.g. `markets=h2h,spreads` = 2 credits for every game that day).

**Budget pacing:** player props (MLB K props) are billed per *event*, not
per day, so they can burn through the monthly quota much faster than the
bulk moneyline/spread calls. Every odds step checks `x-requests-remaining`
(via a free, quota-exempt call to `/v4/sports`) before spending credits:
- Bulk h2h/spreads/totals calls run whenever remaining credits are above a
  small floor (10) — cheap enough (~200/month across all three sports) that
  they're effectively always on.
- Props calls additionally require being *on pace* for an even 500-credits-
  across-the-month budget (`remaining >= 500 * days_left_in_month / days_in_month`).
  If usage has run ahead of pace, props fall back to the existing
  WebSearch-based method for the rest of the month rather than exhausting
  the quota early — the point is to make the free tier last the whole month,
  not front-load it.

If a specific game/fighter/pitcher has no bookmaker line in the API response,
that one entry falls back to the scrape/WebSearch method rather than failing
the whole step.

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

## Known gaps in the MLB record (2026-10-22)

- **8/28 Yankees ML -165 1u (W, +0.61u)** and **8/31 Braves ML -163 1u (L,
  -1.00u)** were texted, but the routine wrote them to `picks/TODAY.json`, so
  neither reached the sheet. 8/31's grade exists; neither picks file does.
- **Never graded:** 7/19 A's ML +125 0.75u (the routine wrote "A's", which no
  grader matches; the prompts now say "Athletics"), 8/20 Rays ML -170 1u, and
  8/1 Yankees ML and Dodgers ML (doubleheader splits, still PENDING).
- **10/4 Rays ML** was removed on 10/6: the Rays had no game that day.

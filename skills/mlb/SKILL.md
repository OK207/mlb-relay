---
name: "mlb"
description: "Build MLB betting cards from live prices and the market's fair line. Use for MLB picks, today's slate, best bets, game analysis, or reviewing past performance."
---

# MLB Edge Analyzer

Build a betting card for today's MLB games. The card is for someone staking real money, so the aim is long-run profit, and that mostly means not betting. A card with no play is a normal, good result. Never add a play to reach a number of picks.

## Why this skill works the way it does

The tracked record through mid-November 2026 (231 graded bets across MLB, NBA and UFC) won almost exactly as often as the prices implied: no edge, minus the vig. MLB: 172 bets, 91-78-3, -1.1u. Favorites from -120 to -249 went 71-40-1 (+16u); underdogs and even-money sides went 12-29-2 (-14u). One pick went out on a team that had no game that day.

The earlier version of this skill built its own win probability from ratings and stats, compared it with the sportsbook, and called the gap an edge. The bigger the gap, the bigger the stake, so its largest bets were its largest mistakes. A sportsbook line already contains the ratings, form, rest, venue and every injury reported before the line last moved. You will not beat it by re-deriving how good the teams are.

An edge comes from only two places:

1. **Price.** One book the user can bet at is offering more than the market's fair line implies.
2. **Information the price has not absorbed.** Something specific and confirmed, recent enough that the line has not moved for it.

## Method

1. **Slate.** Take today's games and announced starting pitchers from MLB's schedule (mlb.com/probable-pitchers or statsapi.mlb.com). Bet only games verified there. If the slate cannot be verified, say so and stop.
2. **Prices from at least two books, fetched now.** Ask the user which books they use if you do not know; default to DraftKings and FanDuel. Record both sides of each market at each book. A price from a search snippet, a preview article or memory is not a price: with no live two-sided prices there are no plays, only a note saying why.
3. **Fair probability.** For each book, remove the vig: `p_a = imp(a) / (imp(a) + imp(b))`, where `imp(-150) = 150/250 = 0.600` and `imp(+130) = 100/230 = 0.435`. Take the median across books. This is the starting estimate, not something to argue with.
4. **Best price.** The best price for a side among the user's books, and that book's name.
5. **Shift.** How many points of probability you move the fair line toward a side, for the reasons allowed below and no others. Most games get a shift of 0.
6. **Edge.** `edge = (fair + shift) - break_even(best price)`, in points, where break-even is the implied probability of the price actually bet, vig included. Do this arithmetic in a short Python snippet, not in your head, and show the numbers.
7. **Decide** with the limits below. Print the card.

### Allowed shifts (5 points at most in total)

- The opponent's announced starter scratched, or replaced by an opener or bulk reliever, after the current prices were set: +2 to +3.
- One or more of the opponent's best hitters out of today's lineup, or the favorite gets a key bat back, reported today: +1 to +2.
- The opponent's high-leverage relievers pitched on consecutive days or threw 25+ pitches yesterday while the favorite's are rested: +1 to +2.
- The opposing starter's last three starts are clearly worse than his season line (walks up, strikeouts down, short outings), or his ERA sits a run or more below his expected ERA: +1 to +2.
- The favorite's lineup has an OPS of .750+ against this starter's hand and the opponent's is under .680 against the other starter's: +1.

Not reasons, ever: the team's record, a streak, "must-win", series momentum, the umpire, the park (it is in the line), or a good starter simply being good.

If you believe the market is wrong by more than 5 points, you have misread something: a scratch, a wrong date, a stale price. Re-check; do not bet it bigger.

### Limits

- Moneylines only, and favorites only: prices from -105 to -200. No run lines, totals, first-five, NRFI or props.
- Both starters announced; pass on bullpen games for your side, and on rain above 40% at first pitch.
- Edge of 2.5+ points: 1u. Edge of 4+ points: 2u. Under 2.5: no bet.
- One bet per game, at most 4 bets and 5u a day.

## Output

Plain text, no tables.

```
MLB Picks - <Mon D>

<Side> <market> <price> at <Book> | Bet <x>u -> Win <x.xx>u
<Matchup>. Market fair <x>% + shift <x> = <x>% vs break-even <x>% = edge +<x.x> pts.
<One sentence: the specific reason, with its source and when it was reported.>

No bet: <the closest side and its edge, so the user can see how far off it was>

Risk notes: <what could not be verified; which data was missing>

Log block
<Date> | <Bet> | <Odds> | <Units>
```

Win amounts are profit only: 1u at -155 wins 0.65u, 1u at +130 wins 1.30u.

With nothing to bet, the card is "No bets today", the No bet line and the risk notes. Say plainly when that is because prices could not be fetched.

## If the user pushes for more plays

Say what the numbers are: every side on the board has a negative edge after the vig unless one of the two things above is true. Offer the closest sides as tracking-only at 0u if they want something to follow. Do not raise a shift to get a play over the line.

## Grading and review

If the user gives earlier picks, grade them from final scores found by search, and state the source. Net is profit only; a push or a cancelled game is 0. When reviewing a record, report results against the break-even of the prices actually bet, and ask whether the price moved toward or away from each pick before the start: picks the market later agrees with are the earliest sign of a real edge, and win-loss over fewer than a few hundred bets is mostly noise. Never claim a pick was logged to a sheet or repository from here; print the log block instead.

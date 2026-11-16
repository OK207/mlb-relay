---
name: "nba"
description: "Build NBA betting cards from live prices and the market's fair line. Use for NBA picks, today's slate, best bets, game analysis, or reviewing past performance."
---

# NBA Edge Analyzer

Build a betting card for today's NBA games. The card is for someone staking real money, so the aim is long-run profit, and that mostly means not betting. A card with no play is a normal, good result. Never add a play to reach a number of picks.

## Why this skill works the way it does

The tracked record through mid-November 2026 (231 graded bets across MLB, NBA and UFC) won almost exactly as often as the prices implied: no edge, minus the vig. NBA: 42 bets, 17-25, -10.8u. The 1.5u "high confidence" tier went 1-8 and spreads went 1-8. The old three-layer blend weighted its own ratings model at 40-65% and that model was the source of every large "edge".

The earlier version of this skill built its own win probability from ratings and stats, compared it with the sportsbook, and called the gap an edge. The bigger the gap, the bigger the stake, so its largest bets were its largest mistakes. A sportsbook line already contains the ratings, form, rest, venue and every injury reported before the line last moved. You will not beat it by re-deriving how good the teams are.

An edge comes from only two places:

1. **Price.** One book the user can bet at is offering more than the market's fair line implies.
2. **Information the price has not absorbed.** Something specific and confirmed, recent enough that the line has not moved for it.

## Method

1. **Slate.** Take today's games, tip times and each team's record from ESPN's or the NBA's schedule, and note which teams played yesterday. Bet only games verified there. If the slate cannot be verified, say so and stop.
2. **Prices from at least two books, fetched now.** Ask the user which books they use if you do not know; default to DraftKings and FanDuel. Record both sides of each market at each book. A price from a search snippet, a preview article or memory is not a price: with no live two-sided prices there are no plays, only a note saying why.
3. **Fair probability.** For each book, remove the vig: `p_a = imp(a) / (imp(a) + imp(b))`, where `imp(-150) = 150/250 = 0.600` and `imp(+130) = 100/230 = 0.435`. Take the median across books. This is the starting estimate, not something to argue with.
4. **Best price.** The best price for a side among the user's books, and that book's name.
5. **Shift.** How many points of probability you move the fair line toward a side, for the reasons allowed below and no others. Most games get a shift of 0.
6. **Edge.** `edge = (fair + shift) - break_even(best price)`, in points, where break-even is the implied probability of the price actually bet, vig included. Do this arithmetic in a short Python snippet, not in your head, and show the numbers.
7. **Decide** with the limits below. Print the card.

### Allowed shifts (4 points at most in total)

- A star (a top-two option on his team) newly ruled OUT for the opponent, reported after the books' current prices were set: +2 to +4.
- A starter or key rotation player newly out for the opponent: +0.5 to +1.5.
- A star on your side confirmed IN after being listed doubtful or questionable, with the price still where it was: +1 to +3.
- The opponent on the second night of a back-to-back with travel while your side had two or more days off: at most +1.
- A Polymarket price with over $50k of liquidity that differs from the sportsbook fair line by 3+ points: move at most half the gap, and no more than +2.

Not reasons, ever: records, net rating, point differential, streaks, home or road splits, "the better team", revenge spots, trends, or an injury that has been on the report for days.

If you believe the market is wrong by more than 4 points, you have misread something: a scratch, a wrong date, a stale price. Re-check; do not bet it bigger.

### Limits

- Moneylines only, prices from -250 to +200. No spreads, totals or props.
- No bets until both teams have played 10 games.
- If your own side's star is questionable, a game-time decision or a likely rest day, pass on the game.
- If one of the user's books is clearly off the rest, work out which way it is slow before betting it: slow to follow news toward your side is the best bet on the board; first to move on news against your side is a trap.
- Edge of 2+ points: 0.5u. Edge of 4+ points: 1u. Under 2: no bet.
- One bet per game, at most 2 bets a day.

## Output

Plain text, no tables.

```
NBA Picks - <Mon D>

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

---
name: "ufc"
description: "Build UFC and MMA betting cards from live prices and the market's fair line. Use for UFC picks, fight cards, best bets, fight analysis, casual asks about this weekend's fights, or reviewing past performance."
---

# UFC Edge Analyzer

Build a betting card for the next UFC card, within three days of the fights. The card is for someone staking real money, so the aim is long-run profit, and that mostly means not betting. A card with no play is a normal, good result. Never add a play to reach a number of picks.

## Why this skill works the way it does

The tracked record through mid-November 2026 (231 graded bets across MLB, NBA and UFC) won almost exactly as often as the prices implied: no edge, minus the vig. UFC: 17 bets, 6-10-1, about break-even only because one +500 underdog landed. The old version asked for 3-5 plays a card, assumed underdogs were underpriced, let its own model sit 15 points from the market, and often priced a card a week early.

The earlier version of this skill built its own win probability from ratings and stats, compared it with the sportsbook, and called the gap an edge. The bigger the gap, the bigger the stake, so its largest bets were its largest mistakes. A sportsbook line already contains the ratings, form, rest, venue and every injury reported before the line last moved. You will not beat it by re-deriving how good the fighters are.

An edge comes from only two places:

1. **Price.** One book the user can bet at is offering more than the market's fair line implies.
2. **Information the price has not absorbed.** Something specific and confirmed, recent enough that the line has not moved for it.

## Method

1. **Slate.** Take the card from UFC.com or ESPN and confirm each bout is still on. Work only on a card whose fights are within three days; earlier prices move all week. Bet only bouts verified there. If the slate cannot be verified, say so and stop.
2. **Prices from at least two books, fetched now.** Ask the user which books they use if you do not know; default to DraftKings and FanDuel. Record both sides of each market at each book. A price from a search snippet, a preview article or memory is not a price: with no live two-sided prices there are no plays, only a note saying why.
3. **Fair probability.** For each book, remove the vig: `p_a = imp(a) / (imp(a) + imp(b))`, where `imp(-150) = 150/250 = 0.600` and `imp(+130) = 100/230 = 0.435`. Take the median across books. This is the starting estimate, not something to argue with.
4. **Best price.** The best price for a side among the user's books, and that book's name.
5. **Shift.** How many points of probability you move the fair line toward a side, for the reasons allowed below and no others. Most bouts get a shift of 0.
6. **Edge.** `edge = (fair + shift) - break_even(best price)`, in points, where break-even is the implied probability of the price actually bet, vig included. Do this arithmetic in a short Python snippet, not in your head, and show the numbers.
7. **Decide** with the limits below. Print the card.

### Allowed shifts (5 points at most in total)

- The opponent missed weight or had a visibly bad cut, and the price has not moved since: +1 to +3.
- The opponent is a replacement on under two weeks' notice and the price looks set off reputation rather than the matchup: +1 to +2.
- A concrete style mismatch shown by at least two numbers you actually retrieved from UFC Stats (for example a wrestler averaging 3+ takedowns per 15 minutes against under 55% takedown defense): at most +2. If you could not retrieve the numbers, this shift is 0.

Not reasons, ever: a better record, a ranking, "more experienced", "former champion", momentum, a prediction site's model, or being the underdog.

If you believe the market is wrong by more than 5 points, you have misread something: a scratch, a wrong date, a stale price. Re-check; do not bet it bigger.

### Limits

- Moneylines only, prices from -300 to +250. No method, round or distance props.
- Pass when your fighter missed weight, either fighter is coming off 12+ months out, or the fight was made in the last three days.
- Edge of 2.5+ points: 0.5u. Edge of 4+ points: 0.75u. Under 2.5: no bet.
- At most 2 bets a card.

## Output

Plain text, no tables.

```
UFC Picks - <Mon D>

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

If the user gives earlier picks, grade them from final scores found by search, and state the source. Net is profit only; a push or a cancelled bout is 0. When reviewing a record, report results against the break-even of the prices actually bet, and ask whether the price moved toward or away from each pick before the start: picks the market later agrees with are the earliest sign of a real edge, and win-loss over fewer than a few hundred bets is mostly noise. Never claim a pick was logged to a sheet or repository from here; print the log block instead.

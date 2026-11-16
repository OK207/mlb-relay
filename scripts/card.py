#!/usr/bin/env python3
"""Turn the analyst's candidates into a card, or reject them.

    python3 scripts/card.py nba /tmp/candidates.json

candidates.json:
    {"picks": [{"id": "<event id from the sheet>", "market": "ML", "side": "home",
                "shift": 2.5, "why": "one sentence, the specific new information"}]}

market is "ML" or "SPREAD"; side is "away" or "home" exactly as the sheet
printed them; shift is how many points of win probability the analyst moves
the market's fair line toward this side (0 if the price alone is the edge).

The price, the book, the fair line, the edge and the stake all come from the
snapshot scripts/sheet.py saved. Nothing here is typed by the analyst, so a
card can never quote a game that is not on the slate, a price nobody offers,
or an edge measured against the wrong number. Rules: config/betting.json.

Writes picks/<sport>/<date>.json (adding to what is already there) and
prints the lines to paste into the message.
"""
import argparse
import json
import sys

import betlib as B

MAX_SNAPSHOT_AGE_MIN = 90


def evaluate(sport: str, snap: dict, cand: dict, r: dict):
    """Returns (pick dict, None) or (None, reason)."""
    ev = next((e for e in snap["events"] if e["id"] == cand.get("id")), None)
    if not ev:
        return None, "that id is not on the sheet"
    game = f"{ev['away']} @ {ev['home']}"
    side = cand.get("side")
    market = str(cand.get("market", "")).upper()
    if side not in ("away", "home"):
        return None, f"{game}: side must be 'away' or 'home'"
    if market not in r["markets"]:
        return None, f"{game}: {market or '?'} is not a market this sport bets ({'/'.join(r['markets'])} only)"
    if ev.get("unverified"):
        return None, f"{game}: not found on ESPN's slate, so it cannot be bet"
    if B.parse_time(ev["commence"]) <= B.now_utc():
        return None, f"{game}: already started"
    m = ev.get("ml" if market == "ML" else "spread", {}).get(side)
    if not m or m.get("best") is None:
        return None, f"{game}: no {market} price at your books"
    if m.get("fair") is None:
        return None, f"{game}: no two-way market to take a fair line from"
    odds = m["best"]
    if not (r["min_odds"] <= odds <= r["max_odds"]):
        return None, (f"{game}: {B.fmt_odds(odds)} is outside the allowed range "
                      f"{B.fmt_odds(r['min_odds'])} to {B.fmt_odds(r['max_odds'])}")
    if market == "SPREAD" and abs(m["point"]) > r.get("max_spread", 99):
        return None, f"{game}: spread {m['point']:+g} is larger than the {r['max_spread']:g} limit"
    need = r.get("min_games_played")
    if need:
        for s in ("away", "home"):
            g = ev.get(s + "_info", {}).get("games")
            if g is None or g < need:
                return None, f"{game}: {ev[s]} has played {g if g is not None else 'an unknown number of'} games (need {need})"
    try:
        shift = float(cand.get("shift", 0))
    except (TypeError, ValueError):
        return None, f"{game}: shift must be a number"
    if abs(shift) > r["max_shift"]:
        return None, (f"{game}: a {shift:+.1f} pt disagreement with the market is past the "
                      f"{r['max_shift']:g} pt limit - treat it as a data error, not an edge")
    why = str(cand.get("why", "")).strip()
    if shift > 0 and len(why) < 15:
        return None, f"{game}: a shift needs its reason in 'why'"
    fair = m["fair"]
    model = fair + shift / 100.0
    edge = 100.0 * (model - B.implied(odds))
    units = B.stake_for(edge, r)
    if units < 0:
        return None, (f"{game}: edge {edge:+.1f} pts at {B.fmt_odds(odds)} is under the "
                      f"{r['tiers'][-1][0]:g} pt minimum (fair {100 * fair:.1f}% + shift {shift:g} "
                      f"vs break-even {100 * B.implied(odds):.1f}%)")
    name = B.short_name(sport, ev[side])
    bet = f"{name} ML" if market == "ML" else f"{name} {m['point']:+g}"
    pick = {"bet": bet, "odds": int(odds), "units": units, "book": m["book"],
            "edge": round(edge, 1), "fair": round(100 * fair, 1), "shift": shift,
            "game": game, "start": ev["commence"], "event_id": ev["id"], "side": side,
            "market": market, "why": why}
    if market == "SPREAD":
        pick["point"] = m["point"]
    if ev.get("espn_id"):
        pick["espn_id"] = ev["espn_id"]
    return pick, None


def format_pick(p: dict) -> str:
    head = f"{p['bet']} {B.fmt_odds(p['odds'])} at {B.book_name(p['book'])}"
    opp = p["game"].replace(" @ ", " at ")
    if p["units"] > 0:
        head += f" | Bet {B.fmt_units(p['units'])}u -> Win {B.profit(p['odds'], p['units']):.2f}u"
    else:
        head += " | Tracking only - not a bet"
    be = 100 * B.implied(p["odds"])
    math = (f"{opp}. Market fair {p['fair']:.1f}%"
            + (f" + {p['shift']:g} = {p['fair'] + p['shift']:.1f}%" if p["shift"] else "")
            + f" vs break-even {be:.1f}% = edge {p['edge']:+.1f} pts.")
    return "\n".join([head, math] + ([p["why"]] if p["why"] else []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sport", choices=sorted(B.SPORTS))
    ap.add_argument("candidates")
    ap.add_argument("--date", default=None, help="slate date; default today ET (UFC: the saved card)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sport, r = a.sport, B.rules(a.sport)

    d = a.date or B.today_et()
    snap = B.read_json(B.lines_path(sport, d))
    if snap is None and sport == "ufc" and not a.date:
        # the card is filed under its fight date, which is rarely today
        files = sorted((B.ROOT / "lines" / "ufc").glob("20??-??-??.json"))
        files = [f for f in files if f.stem >= d]
        snap = B.read_json(files[0]) if files else None
    if snap is None:
        sys.exit(f"REJECTED: no sheet saved for {sport} {d}. Run scripts/sheet.py {sport} first; "
                 "without real prices there are no bets.")
    d = snap["date"]
    age = (B.now_utc() - B.parse_time(snap["fetched_at"])).total_seconds() / 60
    if age > MAX_SNAPSHOT_AGE_MIN:
        sys.exit(f"REJECTED: the sheet is {age:.0f} minutes old. Run scripts/sheet.py {sport} again.")

    doc = json.load(open(a.candidates))
    cands = doc.get("picks", doc) if isinstance(doc, dict) else doc

    path = B.picks_path(sport, d)
    existing = B.unwrap(B.read_json(path, []))
    taken = {p.get("event_id") for p in existing if p.get("event_id")}
    accepted, rejected = [], []
    for c in cands:
        pick, why_not = evaluate(sport, snap, c, r)
        if pick is None:
            rejected.append(why_not)
        elif pick["event_id"] in taken or any(B.bet_key(pick["bet"]) == B.bet_key(p["bet"]) for p in existing):
            rejected.append(f"{pick['game']}: already has a pick on today's card")
        else:
            accepted.append(pick)

    # one bet per game, largest edges first, inside the card's caps
    accepted.sort(key=lambda p: -p["edge"])
    final, seen = [], set(taken)
    n = len(existing)
    used = sum(float(p.get("units") or 0) for p in existing)
    for p in accepted:
        if p["event_id"] in seen:
            rejected.append(f"{p['game']}: one bet per game - kept the larger edge")
        elif n >= r["max_bets"]:
            rejected.append(f"{p['bet']}: the card already has {r['max_bets']} bets (edge {p['edge']:+.1f} pts)")
        elif used + p["units"] > r["max_units"] + 1e-9:
            rejected.append(f"{p['bet']}: would take the card past {r['max_units']:g}u")
        else:
            final.append(p)
            seen.add(p["event_id"])
            n, used = n + 1, used + p["units"]

    print(f"CARD {B.SPORTS[sport]['label']} {d}: {len(final)} accepted, {len(rejected)} rejected"
          + (f", {len(existing)} already on file" if existing else ""))
    for x in rejected:
        print(f"  REJECTED  {x}")
    if final and not a.dry_run:
        allp = existing + final
        if sport == "ufc":
            B.write_json(path, {"event": snap.get("event", ""), "event_date": d, "picks": allp})
        else:
            B.write_json(path, allp)
        print(f"  wrote {path.relative_to(B.ROOT)}")
    print("\n----- PASTE INTO THE MESSAGE -----")
    if final:
        print("\n\n".join(format_pick(p) for p in final))
    else:
        print("(no picks)")


if __name__ == "__main__":
    main()

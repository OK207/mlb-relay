#!/usr/bin/env python3
"""Line check: has the market moved toward today's picks or away from them?

    python3 scripts/clv.py              # every sport with open picks
    python3 scripts/clv.py nba cbb

For each pick whose game has not started, fetches the current prices and
compares the market's fair probability now with what it was when the pick
was made. A pick the market later agrees with (positive "line value") is the
earliest honest sign of an edge: win-loss needs hundreds of bets to say
anything, line value says it in a few dozen. A model whose picks the market
keeps moving away from is not finding anything.

Writes clv/<sport>/<date>.json and prints a block for the text. Costs one
Odds API credit per sport that has open picks (two for cbb); none otherwise.
"""
import argparse
import sys

import betlib as B
import sheet


def open_pick_dates(sport: str) -> list:
    today = B.today_et()
    return [d for d in B.pick_dates(sport) if d >= today] if sport == "ufc" \
        else ([today] if B.picks_path(sport, today).exists() else [])


def check(sport: str, d: str) -> list:
    picks = [p for p in B.unwrap(B.read_json(B.picks_path(sport, d), [])) if p.get("event_id")]
    picks = [p for p in picks if B.parse_time(p["start"]) > B.now_utc()]
    if not picks:
        return []
    snap = sheet.fetch_prices(sport, d if sport != "ufc" else B.today_et())
    by_id = {e["id"]: e for e in snap["events"]}
    pv = B.rules(sport).get("spread_point_value", 3.0)
    rows = []
    for p in picks:
        ev = by_id.get(p["event_id"])
        row = {"bet": p["bet"], "odds": p["odds"], "book": p.get("book"), "fair_then": p["fair"]}
        m = None if not ev else ev.get("ml" if p.get("market", "ML") == "ML" else "spread", {}).get(p["side"])
        if not m or m.get("fair") is None:
            row.update({"clv_pts": None, "note": "no current price"})
            rows.append(row)
            continue
        fair_now = 100 * m["fair"]
        if p.get("market") == "SPREAD" and m.get("point") is not None:
            # value of the number we hold against the number on offer now
            fair_now += pv * (p["point"] - m["point"])
            row["point_now"] = m["point"]
        same_book = m["prices"].get(p.get("book"))
        row.update({"fair_now": round(fair_now, 1), "clv_pts": round(fair_now - p["fair"], 1),
                    "price_now": (same_book if not isinstance(same_book, list) else same_book[1]),
                    "best_now": m["best"], "best_book_now": m["book"]})
        rows.append(row)
    B.write_json(B.ROOT / "clv" / sport / f"{d}.json",
                 {"sport": sport, "date": d, "checked_at": snap["fetched_at"], "picks": rows})
    return rows


def block(sport: str, d: str, rows: list) -> str:
    L = [f"{B.SPORTS[sport]['label']} line check {B.pretty_date(d)}:"]
    for r in rows:
        if r["clv_pts"] is None:
            L.append(f"  {r['bet']} {B.fmt_odds(r['odds'])}: {r['note']}")
            continue
        now = f"now {B.fmt_odds(r['price_now'])}" if r.get("price_now") is not None else "off the board at that book"
        if r.get("point_now") is not None:
            now = f"now {r['point_now']:+g} {B.fmt_odds(r['price_now'])}" if r.get("price_now") is not None else now
        way = "toward us" if r["clv_pts"] > 0.2 else "against us" if r["clv_pts"] < -0.2 else "flat"
        L.append(f"  {r['bet']} {B.fmt_odds(r['odds'])}: {now} | fair {r['fair_then']:.1f}% -> "
                 f"{r['fair_now']:.1f}% ({r['clv_pts']:+.1f} pts, {way})")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sports", nargs="*", default=["mlb", "nba", "cbb", "ufc"])
    a = ap.parse_args()
    out = []
    for sport in a.sports:
        for d in open_pick_dates(sport):
            try:
                rows = check(sport, d)
            except Exception as e:
                print(f"LINE_CHECK_FAILED {sport} {d}: {e}")
                continue
            if rows:
                out.append(block(sport, d, rows))
    if out:
        print("----- LINE CHECK: PASTE INTO THE MESSAGE -----")
        print("\n\n".join(out))
    else:
        print("NO_OPEN_PICKS: nothing to check.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Today's slate with real prices, for one sport.

    python3 scripts/sheet.py nba            # also: cbb, ufc, mlb
    python3 scripts/sheet.py nba --date 2026-11-16

Fetches every US book's price from The Odds API (ODDS_API_KEY), works out the
market's no-vig fair probability per side and the best price at the books in
config/betting.json, adds the facts a card needs (records, rest, injuries,
ratings), saves the snapshot to lines/<sport>/<date>.json and prints one block
per game. scripts/card.py prices every pick from that snapshot, so a bet can
only ever be made on a game and a price that appear here.

Costs 1 Odds API credit (2 for cbb: moneylines and spreads).
"""
import argparse
import datetime as dt
import os
import sys

import betlib as B

MARKETS = {"mlb": "h2h", "nba": "h2h", "ufc": "h2h", "cbb": "h2h,spreads"}


# --------------------------------------------------------------------------
# prices
# --------------------------------------------------------------------------

def _iso(t: dt.datetime) -> str:
    return t.astimezone(B.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def window(sport: str, d: str):
    """Start and end of the slate: not yet started, and on ET date d
    (UFC: within window_days of d, since a card can fall on any day)."""
    day0 = dt.datetime.combine(dt.date.fromisoformat(d), dt.time(0, 0), B.ET)
    start = max(B.now_utc(), day0.astimezone(B.UTC))
    days = B.rules(sport).get("window_days", 0) if sport == "ufc" else 0
    end = day0 + dt.timedelta(days=days + 1, hours=4)   # 4 AM ET catches Hawaii tips
    return start, end.astimezone(B.UTC)


def fetch_prices(sport: str, d: str) -> dict:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("NO_ODDS_API_KEY: ODDS_API_KEY is not set in this environment")
    start, end = window(sport, d)
    url = (f"https://api.the-odds-api.com/v4/sports/{B.SPORTS[sport]['odds_key']}/odds/"
           f"?apiKey={key}&regions=us&markets={MARKETS[sport]}&oddsFormat=american"
           f"&commenceTimeFrom={_iso(start)}&commenceTimeTo={_iso(end)}")
    try:
        body, headers = B.http_get(url)
    except RuntimeError as e:
        raise RuntimeError(str(e).replace(key, "***")) from None
    import json
    raw = json.loads(body)
    mine = B.my_books()
    events = []
    for ev in raw:
        t = B.parse_time(ev["commence_time"])
        if not (start <= t <= end):
            continue                               # started (live prices) or another day
        away, home = ev["away_team"], ev["home_team"]
        ml, sp = {}, {}
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                o = {x["name"]: x for x in mk.get("outcomes", [])}
                if away not in o or home not in o:
                    continue
                if mk["key"] == "h2h":
                    ml[bk["key"]] = (o[away]["price"], o[home]["price"])
                elif mk["key"] == "spreads" and "point" in o[away] and "point" in o[home]:
                    sp[bk["key"]] = ((o[away]["point"], o[away]["price"]),
                                     (o[home]["point"], o[home]["price"]))
        e = {"id": ev["id"], "commence": ev["commence_time"], "date": B.et_date(ev["commence_time"]),
             "away": away, "home": home, "n_books": len(set(ml) | set(sp))}
        if ml:
            e["ml"] = _ml_market(ml, mine)
        if sp:
            e["spread"] = _spread_market(sport, sp, mine)
        if "ml" in e or "spread" in e:
            events.append(e)
    events.sort(key=lambda e: (e["commence"], e["home"]))
    return {"sport": sport, "date": d, "fetched_at": _iso(B.now_utc()),
            "credits_remaining": headers.get("x-requests-remaining"),
            "my_books": mine, "events": events}


def _ml_market(ml: dict, mine: list) -> dict:
    fair_away = B.fair_two_way(list(ml.values()))
    out = {}
    for i, side in enumerate(("away", "home")):
        fair = None if fair_away is None else (fair_away if i == 0 else 1 - fair_away)
        have = [(ml[b][i], b) for b in mine if b in ml]
        best = max(have) if have else None
        out[side] = {"fair": None if fair is None else round(fair, 4),
                     "best": best[0] if best else None, "book": best[1] if best else None,
                     "prices": {b: p[i] for b, p in ml.items()}}
    return out


def _spread_market(sport: str, sp: dict, mine: list) -> dict:
    pv = B.rules(sport).get("spread_point_value", 3.0) / 100.0
    out = {}
    for i, side in enumerate(("away", "home")):
        cons = B.median([v[i][0] for v in sp.values()])
        # cover probability at the consensus number, vig removed
        at_cons = [(v[i][1], v[1 - i][1]) for v in sp.values() if v[i][0] == cons]
        base = B.fair_two_way(at_cons) or 0.5
        have = [(sp[b][i][0], sp[b][i][1], b) for b in mine if b in sp]
        best = max(have) if have else None         # most points first, then best price
        fair = None if not best else base + pv * (best[0] - cons)
        out[side] = {"consensus_point": cons,
                     "point": best[0] if best else None, "best": best[1] if best else None,
                     "book": best[2] if best else None,
                     "fair": None if fair is None else round(min(max(fair, 0.02), 0.98), 4),
                     "prices": {b: list(v[i]) for b, v in sp.items()}}
    return out


# --------------------------------------------------------------------------
# context from ESPN (and Torvik for college)
# --------------------------------------------------------------------------

def _competitors(event: dict) -> dict:
    comp = event["competitions"][0]
    out = {}
    for c in comp["competitors"]:
        rec = next((r["summary"] for r in c.get("records", []) if r.get("summary")), "")
        team = c.get("team", {})
        out[c["homeAway"]] = {"name": team.get("displayName", ""), "short": team.get("shortDisplayName", ""),
                              "location": team.get("location", ""), "record": rec,
                              "rank": (c.get("curatedRank") or {}).get("current")}
    out["neutral"] = bool(comp.get("neutralSite"))
    out["status"] = comp["status"]["type"].get("description", "")
    return out


def _games_played(record: str):
    try:
        return sum(int(x) for x in record.split("-")[:2])
    except Exception:
        return None


def match_espn(sport: str, away: str, home: str, espn_events: list):
    """The ESPN event for an Odds API matchup, or None if it is not clear-cut."""
    scored = []
    for ev in espn_events:
        try:
            c = _competitors(ev)
        except Exception:
            continue
        if "away" not in c or "home" not in c:
            continue
        if sport in ("nba", "mlb"):
            f = lambda full: B.short_name(sport, full)
            straight = float(f(c["away"]["name"]) == f(away) and f(c["home"]["name"]) == f(home))
            flipped = 0.0
        else:
            def s(a, b):
                return max(B.name_score(a["name"], b), B.name_score(a["location"], b) - 0.05)
            straight = min(s(c["away"], away), s(c["home"], home))
            flipped = min(s(c["away"], home), s(c["home"], away))
        scored.append((max(straight, flipped), flipped > straight, ev, c))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < 0.8:
        return None
    if len(scored) > 1 and scored[1][0] > scored[0][0] - 0.03 and scored[0][0] < 1.0:
        return None                                # two candidates too close to call
    return scored[0]


def add_context(sport: str, snap: dict) -> None:
    d = snap["date"]
    notes = snap.setdefault("notes", [])
    if sport == "ufc":
        return _ufc_context(snap)
    if sport == "mlb":
        return                                      # scripts/game_sheet.py covers MLB
    try:
        today = B.espn_scoreboard(sport, d)
    except Exception as e:
        notes.append(f"ESPN slate unavailable: {e}")
        today = []
    b2b = set()
    if sport == "nba":
        y = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        try:
            for ev in B.espn_scoreboard(sport, y):
                for side in ("away", "home"):
                    b2b.add(B.short_name("nba", _competitors(ev)[side]["name"]))
        except Exception as e:
            notes.append(f"yesterday's slate unavailable (no back-to-back flags): {e}")
    standings = _nba_standings(notes) if sport == "nba" else {}
    injuries = _nba_injuries(notes) if sport == "nba" else {}
    torvik = _torvik(d, notes) if sport == "cbb" else []
    for e in snap["events"]:
        m = match_espn(sport, e["away"], e["home"], today)
        if not m:
            e["unverified"] = True                 # not found on ESPN's slate: cannot be bet
            continue
        _, flipped, ev, c = m
        e["espn_id"] = ev["id"]
        e["neutral"] = c["neutral"]
        for side in ("away", "home"):
            src = c["home" if side == "away" else "away"] if flipped else c[side]
            info = {"record": src["record"], "games": _games_played(src["record"])}
            if src.get("rank") and src["rank"] <= 25:
                info["rank"] = src["rank"]
            if sport == "nba":
                nick = B.short_name("nba", e[side])
                info["b2b"] = nick in b2b
                info.update(standings.get(nick, {}))
                info["injuries"] = injuries.get(nick, [])
            if sport == "cbb":
                tv = _torvik_for(e[side], src, torvik)
                if tv:
                    info["torvik"] = tv
            e[side + "_info"] = info
        if sport == "cbb":
            e["torvik_home_margin"] = _torvik_margin(e)
    if sport == "nba" and today:
        st = (today[0].get("season") or {}).get("type")
        snap["season_type"] = st                    # 1 preseason, 2 regular, 3 playoffs


def _nba_standings(notes) -> dict:
    out = {}
    try:
        data = B.http_json("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings")
        for conf in data.get("children", []):
            for ent in conf["standings"]["entries"]:
                s = {x["name"]: x.get("displayValue") for x in ent["stats"]}
                out[B.short_name("nba", ent["team"]["displayName"])] = {
                    "diff": s.get("differential"), "last10": s.get("Last Ten Games"),
                    "home_rec": s.get("Home"), "road_rec": s.get("Road"), "streak": s.get("streak")}
    except Exception as e:
        notes.append(f"standings unavailable: {e}")
    return out


def _nba_injuries(notes) -> dict:
    out = {}
    try:
        data = B.http_json("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries")
        for team in data.get("injuries", []):
            rows = []
            for i in team.get("injuries", []):
                rows.append({"player": i["athlete"]["displayName"], "status": i.get("status"),
                             "updated": (i.get("date") or "")[:16],
                             "note": (i.get("shortComment") or "")[:160]})
            out[B.short_name("nba", team["displayName"])] = rows
    except Exception as e:
        notes.append(f"injury report unavailable: {e}")
    return out


def _torvik(d: str, notes) -> list:
    y = dt.date.fromisoformat(d)
    season = y.year + 1 if y.month >= 10 else y.year
    try:
        rows = B.http_json(f"https://barttorvik.com/{season}_team_results.json")
        return [{"team": r[1], "rank": r[0], "record": r[3], "adj_o": round(r[4], 1),
                 "adj_d": round(r[6], 1), "barthag": round(r[8], 3),
                 "tempo": round(r[44], 1) if len(r) > 44 and isinstance(r[44], (int, float)) else None}
                for r in rows]
    except Exception as e:
        notes.append(f"Torvik ratings unavailable: {e}")
        return []


def _torvik_margin(e: dict):
    """Torvik's projected home margin: efficiency gap x pace, plus 3 for home court."""
    a, h = (e.get(s + "_info", {}).get("torvik") for s in ("away", "home"))
    if not a or not h:
        return None
    pace = ((a.get("tempo") or 68.0) + (h.get("tempo") or 68.0)) / 200.0
    gap = (h["adj_o"] - h["adj_d"]) - (a["adj_o"] - a["adj_d"])
    return round(gap * pace + (0.0 if e.get("neutral") else 3.0), 1)


def _torvik_for(full_name: str, espn_team: dict, torvik: list):
    best, score = None, 0.0
    for t in torvik:
        s = max(B.name_score(t["team"], espn_team.get("location", "")),
                B.name_score(t["team"], espn_team.get("short", "")))
        if s > score:
            best, score = t, s
    return best if score >= 0.9 else None


def _ufc_context(snap: dict) -> None:
    d = snap["date"]
    end = (dt.date.fromisoformat(d) + dt.timedelta(days=B.rules("ufc").get("window_days", 3) + 1)).isoformat()
    try:
        cards = B.espn_scoreboard("ufc", d.replace("-", "") + "-" + end.replace("-", ""))
    except Exception as e:
        snap.setdefault("notes", []).append(f"ESPN card unavailable: {e}")
        cards = []
    bouts = []
    for card in cards:
        n = len(card.get("competitions", []))
        for idx, c in enumerate(card.get("competitions", [])):
            names = [x["athlete"]["displayName"] for x in c.get("competitors", [])]
            recs = {x["athlete"]["displayName"]: next((r["summary"] for r in x.get("records", [])), "")
                    for x in c.get("competitors", [])}
            bouts.append({"event": card["name"], "event_date": B.et_date(card["date"]),
                          "weight": (c.get("type") or {}).get("abbreviation", ""),
                          "order_from_top": n - idx, "names": names, "records": recs,
                          "status": c["status"]["type"].get("name", "")})
    kept = []
    for e in snap["events"]:
        hit = None
        for b in bouts:
            if len(b["names"]) != 2:
                continue
            s1 = min(B.name_score(b["names"][0], e["away"]), B.name_score(b["names"][1], e["home"]))
            s2 = min(B.name_score(b["names"][0], e["home"]), B.name_score(b["names"][1], e["away"]))
            if max(s1, s2) >= 0.85:
                hit = b
                break
        if not hit or hit["status"] != "STATUS_SCHEDULED":
            continue                               # another promotion, or already fought
        e.update({"event": hit["event"], "date": hit["event_date"], "weight": hit["weight"],
                  "order_from_top": hit["order_from_top"]})
        for side in ("away", "home"):
            rec = next((r for n, r in hit["records"].items() if B.name_score(n, e[side]) >= 0.85), "")
            e[side + "_info"] = {"record": rec}
        kept.append(e)
    kept.sort(key=lambda e: (e["date"], e["order_from_top"]))
    snap["events"] = kept
    if kept:
        snap["event"] = kept[0]["event"]
        snap["date"] = kept[0]["date"]              # file the card under its fight date
        snap["events"] = [e for e in kept if e["event"] == snap["event"]]


# --------------------------------------------------------------------------
# printing
# --------------------------------------------------------------------------

def _pct(x):
    return "?" if x is None else f"{100 * x:.1f}%"


def _side_line(sport: str, e: dict, side: str) -> str:
    info = e.get(side + "_info", {})
    bits = [f"{side.upper():4s} {e[side]}"]
    if info.get("rank"):
        bits[0] += f" (#{info['rank']})"
    if info.get("record"):
        bits.append(info["record"])
    if info.get("diff"):
        bits.append(f"pt diff {info['diff']}/g, last10 {info.get('last10')}, "
                    f"home {info.get('home_rec')}, road {info.get('road_rec')}, {info.get('streak')}")
    if info.get("b2b"):
        bits.append("PLAYED YESTERDAY (back-to-back)")
    tv = info.get("torvik")
    if tv:
        bits.append(f"Torvik #{tv['rank']} AdjO {tv['adj_o']} AdjD {tv['adj_d']}")
    return "  " + " | ".join(bits)


def _price_line(e: dict, market: str, brief: bool = False) -> list:
    out = []
    m = e.get(market)
    if not m:
        return out
    for side in ("away", "home"):
        s = m[side]
        if market == "ml":
            head = f"  ML  {e[side]}: fair {_pct(s['fair'])}"
            allp = ", ".join(f"{B.book_name(b)} {B.fmt_odds(p)}" for b, p in sorted(s["prices"].items()))
        else:
            cp = s["consensus_point"]
            head = f"  SPR {e[side]} {cp:+g} (consensus)"
            allp = ", ".join(f"{B.book_name(b)} {p[0]:+g} {B.fmt_odds(p[1])}"
                             for b, p in sorted(s["prices"].items()))
        if s["best"] is None:
            if not brief:
                out.append(f"{head} | NO PRICE AT YOUR BOOKS - cannot be bet | all: {allp}")
            continue
        be = B.implied(s["best"])
        gap = None if s["fair"] is None else 100 * (s["fair"] - be)
        price = (B.fmt_odds(s["best"]) if market == "ml"
                 else f"{s['point']:+g} {B.fmt_odds(s['best'])} (fair {_pct(s['fair'])})")
        out.append(f"{head} | best {price} at {B.book_name(s['book'])}, break-even {_pct(be)}"
                   f" | edge before any shift {gap:+.1f} pts" + ("" if brief else f" | all: {allp}"))
    return out


def bettable(sport: str, e: dict) -> bool:
    """Could any side of this game pass the rules in config/betting.json?"""
    r = B.rules(sport)
    if e.get("unverified"):
        return False
    need = r.get("min_games_played")
    if need and any((e.get(s + "_info", {}).get("games") or 0) < need for s in ("away", "home")):
        return False
    for market, key in (("ML", "ml"), ("SPREAD", "spread")):
        for side in ("away", "home"):
            m = e.get(key, {}).get(side)
            if market not in r["markets"] or not m or m.get("best") is None:
                continue
            if not (r["min_odds"] <= m["best"] <= r["max_odds"]):
                continue
            if key == "spread" and abs(m["point"]) > r.get("max_spread", 99):
                continue
            return True
    return False


def render(sport: str, snap: dict) -> str:
    L = [f"{B.SPORTS[sport]['label']} SHEET {snap['date']}"
         + (f" - {snap['event']}" if snap.get("event") else "")
         + f" | fetched {snap['fetched_at']} | books: {', '.join(B.book_name(b) for b in snap['my_books'])}"
         + f" | Odds API credits left: {snap.get('credits_remaining')}"]
    r = B.rules(sport)
    L.append(f"RULES: markets {'/'.join(r['markets'])}, prices {B.fmt_odds(r['min_odds'])} to "
             f"{B.fmt_odds(r['max_odds'])}, shift at most {r['max_shift']:g} pts, at most "
             f"{r['max_bets']} bets / {r['max_units']:g}u, tiers "
             + ", ".join(f">={t[0]:g} pts = {t[1] * r.get('stake_scale', 1):g}u" for t in r["tiers"]))
    if snap.get("season_type") == 1:
        L.append("PRESEASON - no picks.")
    for n in snap.get("notes", []):
        L.append(f"NOTE: {n}")
    if not snap["events"]:
        L.append("NO GAMES WITH PRICES in the window (none scheduled, or all have started).")
    brief = sport == "cbb"                          # college slates run to 150 games
    hidden = 0
    for i, e in enumerate(snap["events"], 1):
        if brief and not bettable(sport, e):
            hidden += 1
            continue
        L.append("")
        tag = f" | {e['weight']}" if e.get("weight") else ""
        tag += " | neutral site" if e.get("neutral") else ""
        tag += " | NOT VERIFIED ON ESPN'S SLATE - cannot be bet" if e.get("unverified") else ""
        L.append(f"[{i}] id={e['id']}  {e['away']} @ {e['home']}  {B.et_clock(e['commence'])}"
                 f"  ({e['n_books']} books){tag}")
        for side in ("away", "home"):
            L.append(_side_line(sport, e, side))
        L += _price_line(e, "ml", brief) + _price_line(e, "spread", brief)
        if e.get("torvik_home_margin") is not None and e.get("spread"):
            mkt = -e["spread"]["home"]["consensus_point"]
            L.append(f"  TORVIK projects {e['home']} by {e['torvik_home_margin']:+g}; the market says "
                     f"{mkt:+g} (gap {e['torvik_home_margin'] - mkt:+.1f} toward "
                     f"{e['home'] if e['torvik_home_margin'] > mkt else e['away']})")
        if sport == "nba":
            for side in ("away", "home"):
                inj = e.get(side + "_info", {}).get("injuries") or []
                cut = (dt.date.fromisoformat(snap["date"]) - dt.timedelta(days=2)).isoformat()
                new = [x for x in inj if x["updated"][:10] >= cut]
                if inj:
                    L.append(f"  INJ {B.short_name('nba', e[side])}: "
                             + ("; ".join(f"{x['player']} {x['status']} (updated {x['updated'][5:10]})"
                                          for x in new) or "nothing new")
                             + f" | {len(inj) - len(new)} older, already in the price")
    if hidden:
        L.append("")
        L.append(f"{hidden} more game(s) not shown: nothing in them can pass the rules "
                 "(no price at your books, outside the price or spread range, too few games played, "
                 "or not verified on ESPN's slate).")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sport", choices=sorted(B.SPORTS))
    ap.add_argument("--date", default=B.today_et())
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    try:
        snap = fetch_prices(a.sport, a.date)
    except B.Blocked as e:
        print(f"PRICES_UNAVAILABLE: {e}. No real prices means no bets today.")
        sys.exit(2)
    except RuntimeError as e:
        print(f"PRICES_UNAVAILABLE: {e}. No real prices means no bets today.")
        sys.exit(2)
    add_context(a.sport, snap)
    text = render(a.sport, snap)
    if not a.no_save:
        if a.sport == "cbb":                        # keep the saved file small
            for e in snap["events"]:
                for key in ("ml", "spread"):
                    for side in ("away", "home"):
                        e.get(key, {}).get(side, {}).pop("prices", None)
        B.write_json(B.lines_path(a.sport, snap["date"]), snap)
    print(text)


if __name__ == "__main__":
    main()

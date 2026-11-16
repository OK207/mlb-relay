#!/usr/bin/env python3
"""Grade every ungraded pick from official final scores.

    python3 scripts/grade.py nba            # also: mlb, cbb, ufc, all
    python3 scripts/grade.py nba --date 2026-11-15
    python3 scripts/grade.py mlb --days 400 # reach further back than 30 days

Scores come from ESPN's scoreboard API (MLB strikeout props from MLB's own
boxscores), never from a search summary. A bet is graded only when its game
is final; anything else stays PENDING and is picked up by the next run. A
grade already on file as W, L or P is never changed.

net is profit only: 1u at -155 wins +0.65, 1u at +130 wins +1.30, a loss is
minus the stake, a push or a cancelled game is 0.
"""
import argparse
import datetime as dt
import re
import sys

import betlib as B

FINAL = ("STATUS_FINAL", "STATUS_FULL_TIME")
VOID = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED")


def _teams(sport: str, comp: dict) -> list:
    out = []
    for c in comp.get("competitors", []):
        if sport == "ufc":
            out.append({"name": c["athlete"]["displayName"], "location": "",
                        "score": None, "winner": c.get("winner")})
        else:
            t = c.get("team", {})
            try:
                score = float(c.get("score"))
            except (TypeError, ValueError):
                score = None
            out.append({"name": t.get("displayName", ""), "location": t.get("location", ""),
                        "score": score, "winner": c.get("winner")})
    return out


def _is(sport: str, team: dict, name: str) -> bool:
    if sport in ("nba", "mlb"):
        return B.norm(B.short_name(sport, team["name"])) == B.norm(name) \
            or B.norm(team["name"]) == B.norm(name)
    if sport == "ufc":
        full, want = B.norm(team["name"]).split(), B.norm(name).split()
        return full[-len(want):] == want or B.name_score(team["name"], name) >= 0.9
    return max(B.name_score(team["name"], name), B.name_score(team["location"], name)) >= 0.9


def find_games(sport: str, events: list, names: list, pick: dict) -> list:
    """Competitions on these dates that involve every name in `names`."""
    hits = []
    for ev in events:
        for comp in ev.get("competitions", []):
            teams = _teams(sport, comp)
            if pick.get("espn_id") and str(ev.get("id")) == str(pick["espn_id"]) and sport != "ufc":
                return [(comp, teams)]
            if all(any(_is(sport, t, n) for t in teams) for n in names):
                hits.append((comp, teams))
    if len(hits) > 1 and pick.get("start"):            # doubleheader: nearest start time
        t0 = B.parse_time(pick["start"])
        hits.sort(key=lambda h: abs((B.parse_time(h[0]["date"]) - t0).total_seconds()))
        hits = hits[:1]
    return hits


def grade_bet(sport: str, pick: dict, events: list, all_final: bool):
    """Returns (outcome, note). outcome in W / L / P / PENDING."""
    bet = pick["bet"].strip()
    m_k = re.match(r"^(.+?) K (Over|Under) (\d+(?:\.\d+)?)$", bet)
    m_tot = re.match(r"^(.+?)/(.+?) (Over|Under) (\d+(?:\.\d+)?)$", bet)
    m_ml = re.match(r"^(.+?) ML\b", bet)
    m_sp = re.match(r"^(.+?) ([+-]\d+(?:\.\d+)?)$", bet)
    if m_k:
        return grade_k_prop(pick, m_k)
    if m_tot:
        names = [m_tot.group(1), m_tot.group(2)]
    elif m_ml:
        names = [m_ml.group(1)]
    elif m_sp:
        names = [m_sp.group(1)]
    else:
        return "PENDING", "bet format not recognised - grade by hand"
    games = find_games(sport, events, names, pick)
    if not games:
        if sport == "ufc" and all_final:
            return "P", "bout did not take place - stake returned"
        return "PENDING", "game not found on the scoreboard"
    if len(games) > 1:
        outs = {_settle(sport, c, t, names, m_tot, m_ml, m_sp)[0] for c, t in games}
        if len(outs) == 1 and outs != {"PENDING"}:
            return outs.pop(), "doubleheader, same result both games"
        return "PENDING", "two games match this bet (doubleheader) - grade by hand"
    comp, teams = games[0]
    return _settle(sport, comp, teams, names, m_tot, m_ml, m_sp)


def _settle(sport, comp, teams, names, m_tot, m_ml, m_sp):
    status = comp["status"]["type"].get("name", "")
    if status in VOID:
        return "P", "postponed or cancelled - stake returned"
    if status not in FINAL:
        return "PENDING", "not final yet"
    if sport == "ufc":
        mine = next(t for t in teams if _is(sport, t, names[0]))
        if not any(t["winner"] for t in teams):
            return "P", "draw or no contest"
        return ("W" if mine["winner"] else "L"), ""
    if any(t["score"] is None for t in teams) or len(teams) != 2:
        return "PENDING", "final but no score on the feed"
    if m_tot:
        total, line = teams[0]["score"] + teams[1]["score"], float(m_tot.group(4))
        if total == line:
            return "P", ""
        return ("W" if (total > line) == (m_tot.group(3) == "Over") else "L"), ""
    mine = next(t for t in teams if _is(sport, t, names[0]))
    other = next(t for t in teams if t is not mine)
    margin = mine["score"] - other["score"]
    if m_ml:
        return ("W" if margin > 0 else "L" if margin < 0 else "P"), ""
    adj = margin + float(m_sp.group(2))
    return ("W" if adj > 0 else "L" if adj < 0 else "P"), ""


def grade_k_prop(pick: dict, m) -> tuple:
    """MLB pitcher strikeouts, from MLB's boxscores for the pick's date."""
    d = pick["_date"]
    last, over, line = B.norm(m.group(1)), m.group(2) == "Over", float(m.group(3))
    try:
        sched = B.http_json(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}")
        found = []
        for day in sched.get("dates", []):
            for g in day.get("games", []):
                if g["status"].get("abstractGameState") != "Final":
                    continue
                box = B.http_json(f"https://statsapi.mlb.com/api/v1/game/{g['gamePk']}/boxscore")
                for side in ("away", "home"):
                    for p in box["teams"][side]["players"].values():
                        st = p.get("stats", {}).get("pitching", {})
                        if st.get("gamesStarted") and B.norm(p["person"]["fullName"]).split()[-len(last.split()):] == last.split():
                            found.append(st.get("strikeOuts"))
    except Exception as e:
        return "PENDING", f"boxscores unavailable: {e}"
    if len(found) != 1 or found[0] is None:
        return "PENDING", "starter not found in a final boxscore" if not found else "two starters share that name - grade by hand"
    k = found[0]
    if k == line:
        return "P", f"{k} K"
    return ("W" if (k > line) == over else "L"), f"{k} K"


def grade_date(sport: str, d: str, cache: dict):
    picks = B.unwrap(B.read_json(B.picks_path(sport, d), []))
    if not picks:
        return None
    old = {B.bet_key(g["bet"]): g for g in B.unwrap(B.read_json(B.grades_path(sport, d), []))}
    if all(old.get(B.bet_key(p["bet"]), {}).get("outcome") in ("W", "L", "P") for p in picks):
        return None
    if d not in cache:
        if sport == "ufc":                          # a card can run past midnight UTC
            nxt = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
            cache[d] = B.espn_scoreboard(sport, d.replace("-", "") + "-" + nxt.replace("-", ""))
        else:                                       # ESPN files games under their ET date
            cache[d] = B.espn_scoreboard(sport, d)
    events = cache[d]
    all_final = bool(events) and all(c["status"]["type"].get("name") in FINAL + VOID
                                     for ev in events for c in ev.get("competitions", [])
                                     if B.et_date(c.get("date", ev["date"])) == d)
    grades, new = [], []
    for p in picks:
        prev = old.get(B.bet_key(p["bet"]))
        if prev and prev.get("outcome") in ("W", "L", "P"):
            grades.append(prev)
            continue
        outcome, note = grade_bet(sport, dict(p, _date=d), events, all_final)
        units = float(p.get("units") or 0)
        net = B.profit(p["odds"], units) if outcome == "W" else -units if outcome == "L" else 0.0
        g = {"bet": p["bet"], "odds": p["odds"], "units": p["units"], "outcome": outcome, "net": round(net, 2)}
        grades.append(g)
        new.append((g, note))
    if any(g["outcome"] != "PENDING" for g, _ in new) or not B.grades_path(sport, d).exists():
        B.write_json(B.grades_path(sport, d), grades)
    return grades, new


def results_block(sport: str, d: str, grades: list, new: list) -> str:
    lab = B.SPORTS[sport]["label"]
    L = [f"{lab} Results {B.pretty_date(d)}:"]
    notes = {g["bet"]: n for g, n in new}
    w = l = p = 0
    net = 0.0
    for g in grades:
        o = g["outcome"]
        head = f"  {o if o != 'PENDING' else '?':1s}  {g['bet']} {B.fmt_odds(g['odds'])} | {B.fmt_units(g['units'])}u -> "
        if o == "PENDING":
            L.append(head + f"pending ({notes.get(g['bet']) or 'not final'})")
            continue
        w, l, p = w + (o == "W"), l + (o == "L"), p + (o == "P")
        net += g["net"]
        L.append(head + (f"{g['net']:+.2f}u" if o != "P" else "0u (push)")
                 + (f" [{notes[g['bet']]}]" if notes.get(g["bet"]) else ""))
    L.append(f"Day: {net:+.2f}u ({w}W-{l}L" + (f"-{p}P" if p else "") + ")")
    return "\n".join(L)


def run(sport: str, only_date, days: int) -> bool:
    """Grade one sport. Returns True if anything new was settled."""
    today = B.today_et()
    floor = (dt.date.fromisoformat(today) - dt.timedelta(days=days)).isoformat()
    dates = [only_date] if only_date else [d for d in B.pick_dates(sport) if floor <= d <= today]
    cache, blocks, pending = {}, [], 0
    for d in dates:
        try:
            res = grade_date(sport, d, cache)
        except B.Blocked as e:
            print(f"SCORES_UNAVAILABLE: {e}")
            return False
        except Exception as e:
            print(f"SCORES_UNAVAILABLE for {sport} {d}: {e}")
            continue
        if not res:
            continue
        grades, new = res
        pending += sum(g["outcome"] == "PENDING" for g, _ in new)
        if any(g["outcome"] != "PENDING" for g, _ in new):
            blocks.append(results_block(sport, d, grades, new))
    if blocks:
        print("----- NEW RESULTS: PASTE INTO THE MESSAGE -----")
        print("\n\n".join(blocks))
        print("\n" + B.record_line(sport))
    else:
        print(f"NO_NEW_RESULTS {sport}" + (f" ({pending} bet(s) still pending)" if pending else ""))
    return bool(blocks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sport", choices=sorted(B.SPORTS) + ["all"])
    ap.add_argument("--date", help="grade only this date")
    ap.add_argument("--days", type=int, default=30, help="how far back to look for ungraded picks")
    a = ap.parse_args()
    for sport in (sorted(B.SPORTS) if a.sport == "all" else [a.sport]):
        run(sport, a.date, a.days)


if __name__ == "__main__":
    main()

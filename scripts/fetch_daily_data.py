#!/usr/bin/env python3
"""
fetch_daily_data.py — Pre-fetch MLB daily data bundle for the CCR agent.
Runs in GitHub Actions where all sports domains are accessible.
Writes data/YYYY-MM-DD.json to the relay repo.

Sources:
  - Slate + SPs + Standings:  statsapi.mlb.com  (JSON — always works)
    (also: SP handedness, HP umpire once assigned, bullpen usage, team splits)
  - SP stats:                  baseballsavant.mlb.com CSV  (+ MLB Stats API fallback)
  - Odds, every book:          The Odds API when ODDS_API_KEY is set
  - Odds + SP context:         covers.com  (Playwright — JS-rendered)
  - Weather:                   wttr.in JSON per venue  (no JS needed)
  - Weather at first pitch:    open-meteo.com hourly forecast (no key)
  - Lineups:                   rotowire.com  (requests — HTML partially works)

Each game in "slate" carries everything the picks routines need for it, so a
routine never has to join tables by team name:
  odds (best price per side and which book has it, no-vig fair probability),
  hp_umpire, bullpen_away/bullpen_home, weather_first_pitch.
The older top-level keys (odds, weather, lineups, ...) are kept as they were.
"""
import argparse, csv, io, json, os, re, sys, urllib.parse
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Run: pip install requests beautifulsoup4")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def get(url, timeout=25, **kwargs):
    r = SESSION.get(url, timeout=timeout, **kwargs)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# SLATE + PROBABLE PITCHERS  (statsapi.mlb.com)
# ---------------------------------------------------------------------------

def _implied(o) -> float:
    """Break-even probability of an American price, vig included."""
    return abs(o) / (abs(o) + 100) if o < 0 else 100 / (o + 100)


def _ip_to_outs(ip) -> int:
    whole, _, frac = str(ip or "0").partition(".")
    try:
        return int(whole or 0) * 3 + int(frac or 0)
    except ValueError:
        return 0


def fetch_slate(d: str) -> list:
    # gameType S is included so the routines can see Spring Training and stop,
    # instead of mistaking an empty regular-season slate for an off day.
    base = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={d}&gameType=R,F,D,L,W,S"
    )
    data = None
    # venue(location) and officials are richer hydrations; fall back to the
    # plain one rather than lose the whole slate if either is ever refused.
    for hydrate in ("probablePitcher,venue(location),team,officials",
                    "probablePitcher,venue,team"):
        try:
            data = SESSION.get(f"{base}&hydrate={hydrate}", timeout=20).json()
            if "dates" in data:
                break
        except Exception as e:
            print(f"  schedule hydrate={hydrate} failed: {e}")
            data = None
    if data is None:
        raise RuntimeError("schedule unavailable")
    games = []
    for day in data.get("dates", []):
        for g in day.get("games", []):
            at = g["teams"]["away"]
            ht = g["teams"]["home"]

            def sp(t):
                p = t.get("probablePitcher", {})
                if not p:
                    return {"name": "TBD", "id": None, "throws": "?"}
                return {
                    "name": p.get("fullName", "TBD"),
                    "id": p.get("id"),
                    "throws": p.get("pitchHand", {}).get("code", "?"),
                }

            time_et = ""
            dt_str = g.get("gameDate", "")
            if dt_str:
                try:
                    dt_u = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    off = -4 if 3 <= dt_u.month <= 11 else -5
                    time_et = (dt_u + timedelta(hours=off)).strftime("%H:%M")
                except Exception:
                    pass

            hp_umpire = next(
                (o.get("official", {}).get("fullName")
                 for o in g.get("officials", []) or []
                 if o.get("officialType") == "Home Plate"),
                None,
            )
            coords = ((g.get("venue", {}) or {}).get("location", {}) or {}).get(
                "defaultCoordinates", {}) or {}

            games.append({
                "game_id": g.get("gamePk"),
                "time_et": time_et,
                "game_time_utc": dt_str,
                "game_type": g.get("gameType", ""),
                "game_number": g.get("gameNumber", 1),
                "series": g.get("seriesDescription", ""),
                "away_team": at.get("team", {}).get("name", "?"),
                "home_team": ht.get("team", {}).get("name", "?"),
                "away_nick": at.get("team", {}).get("teamName", ""),
                "home_nick": ht.get("team", {}).get("teamName", ""),
                "venue": g.get("venue", {}).get("name", ""),
                "venue_lat": coords.get("latitude"),
                "venue_lon": coords.get("longitude"),
                "status": g.get("status", {}).get("detailedState", ""),
                "hp_umpire": hp_umpire,
                "sp_away": sp(at),
                "sp_home": sp(ht),
            })

    # The schedule's probablePitcher carries no handedness, which is why every
    # bundle so far said throws "?". One people lookup fills it for the slate.
    ids = [gm[s]["id"] for gm in games for s in ("sp_away", "sp_home") if gm[s]["id"]]
    if ids:
        try:
            people = SESSION.get(
                "https://statsapi.mlb.com/api/v1/people?personIds="
                + ",".join(str(i) for i in ids),
                timeout=20,
            ).json().get("people", [])
            hand = {p["id"]: p.get("pitchHand", {}).get("code", "?") for p in people}
            for gm in games:
                for s in ("sp_away", "sp_home"):
                    if gm[s]["id"] in hand:
                        gm[s]["throws"] = hand[gm[s]["id"]]
        except Exception as e:
            print(f"  pitcher handedness lookup failed: {e}")
    return games


# ---------------------------------------------------------------------------
# STANDINGS  (statsapi.mlb.com)
# ---------------------------------------------------------------------------

def fetch_standings(year: str) -> dict:
    url = (
        f"https://statsapi.mlb.com/api/v1/standings"
        f"?leagueId=103,104&season={year}&standingsTypes=regularSeason"
    )
    data = SESSION.get(url, timeout=20).json()
    teams = {}
    for record in data.get("records", []):
        div = record.get("division", {}).get("name", "")
        for tr in record.get("teamRecords", []):
            name = tr["team"]["name"]
            teams[name] = {
                "wins": tr["wins"],
                "losses": tr["losses"],
                "pct": float(tr.get("winningPercentage", 0) or 0),
                "division": div,
                "gb": tr.get("gamesBack", "-"),
            }
    return teams


# ---------------------------------------------------------------------------
# SP STATS  (Baseball Savant CSV; MLB Stats API fallback)
# ---------------------------------------------------------------------------

def fetch_sp_stats(year: str) -> dict:
    url = (
        f"https://baseballsavant.mlb.com/leaderboard/custom"
        f"?year={year}&type=pitcher&filter=&sort=4&order=desc"
        f"&min=5&selections=p_era,xera,k_percent,bb_percent,p_formatted_ip&csv=true"
    )
    try:
        text = SESSION.get(
            url,
            timeout=25,
            headers={
                "Accept": "text/csv,text/plain,*/*",
                "Referer": "https://baseballsavant.mlb.com/leaderboard/custom",
            },
        ).text
        # Validate: real CSV starts with the header line
        if text.strip().startswith('"last_name, first_name"') or text.strip().startswith('last_name'):
            reader = csv.DictReader(io.StringIO(text))
            stats = {}
            for row in reader:
                name = row.get("last_name, first_name", "")
                if "," in name:
                    last, first = name.split(",", 1)
                    name = f"{first.strip()} {last.strip()}"
                if name:
                    stats[name] = {
                        "era":   row.get("p_era", ""),
                        "xera":  row.get("xera", ""),
                        "k_pct": row.get("k_percent", ""),
                        "bb_pct":row.get("bb_percent", ""),
                        "ip":    row.get("p_formatted_ip", ""),
                        "source": "savant",
                    }
            if stats:
                return stats
        print("  Savant returned HTML — falling back to MLB Stats API")
    except Exception as e:
        print(f"  Savant error: {e} — falling back to MLB Stats API")

    # Fallback: MLB Stats API season pitching stats
    return _fetch_sp_stats_mlbapi(year)


def _fetch_sp_stats_mlbapi(year: str) -> dict:
    """Basic ERA + K/BB from statsapi.mlb.com as Savant fallback."""
    url = (
        f"https://statsapi.mlb.com/api/v1/stats"
        f"?stats=season&group=pitching&season={year}&limit=300"
        f"&sortStat=earnedRunAverage&order=asc"
    )
    data = SESSION.get(url, timeout=20).json()
    stats = {}
    for entry in data.get("stats", [{}])[0].get("splits", []):
        player = entry.get("player", {})
        name = player.get("fullName", "")
        s = entry.get("stat", {})
        if name:
            stats[name] = {
                "era":   s.get("era", ""),
                "xera":  "",
                "k_pct": "",
                "bb_pct":"",
                "ip":    s.get("inningsPitched", ""),
                "k9":    s.get("strikeoutsPer9Inn", ""),
                "bb9":   s.get("walksPer9Inn", ""),
                "source": "mlbapi",
            }
    return stats


# ---------------------------------------------------------------------------
# ODDS + SP CONTEXT  (covers.com via Playwright)
# ---------------------------------------------------------------------------

def fetch_odds_playwright() -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright not installed — skipping odds")
        return {}

    odds = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        try:
            page.goto(
                "https://www.covers.com/sport/baseball/mlb/odds",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            # Wait for game rows to actually render (JS-driven)
            page.wait_for_selector(".oddsGameRow", timeout=30000)
            game_rows = page.query_selector_all(".oddsGameRow")

            for row in game_rows:
                try:
                    cells = row.query_selector_all(".td-cell")
                    if len(cells) < 5:
                        continue

                    def parse_team_cell(cell):
                        txt = cell.inner_text()
                        parts = [p.strip() for p in txt.split("\n") if p.strip()]
                        abbr = parts[0] if parts else "?"
                        sp_name = parts[1] if len(parts) > 1 else "TBD"
                        hand, era = "?", None
                        for part in parts:
                            m = re.search(r'\(([LR]),\s*([\d.]+)\)', part)
                            if m:
                                hand, era = m.group(1), float(m.group(2))
                        return abbr, sp_name, hand, era

                    away_abbr, away_sp, away_hand, away_era = parse_team_cell(cells[1])
                    home_abbr, home_sp, home_hand, home_era = parse_team_cell(cells[2])

                    away_mls, home_mls = [], []
                    for i, cell in enumerate(cells[3:]):
                        txt = cell.inner_text().strip()
                        m = re.match(r'^([+-]?\d{3,4})', txt)
                        if m:
                            val = int(m.group(1))
                            if i % 2 == 0:
                                away_mls.append(val)
                            else:
                                home_mls.append(val)

                    # Cells past the first pair are not reliably moneylines:
                    # run-line and total juice gets picked up too, which is how
                    # "best" prices like +118 on both sides got into bundles.
                    # Keep only pairs whose two sides form a real two-way
                    # market (implied probabilities summing to 100-110%).
                    pairs = [
                        (a, h) for a, h in zip(away_mls, home_mls)
                        if 1.0 <= _implied(a) + _implied(h) <= 1.10
                    ]
                    if not pairs:
                        continue

                    key = f"{away_abbr} vs {home_abbr}"
                    odds[key] = {
                        "away_abbr": away_abbr,
                        "home_abbr": home_abbr,
                        "away_ml":   pairs[0][0],
                        "home_ml":   pairs[0][1],
                        "away_ml_best": max(a for a, _ in pairs),
                        "home_ml_best": max(h for _, h in pairs),
                        "away_sp": {"name": away_sp, "throws": away_hand, "era": away_era},
                        "home_sp": {"name": home_sp, "throws": home_hand, "era": home_era},
                        "books_count": len(pairs),
                    }
                except Exception:
                    continue
        finally:
            browser.close()

    return odds


# ---------------------------------------------------------------------------
# WEATHER  (wttr.in JSON per venue — no JS needed)
# ---------------------------------------------------------------------------

# Hardcoded venue → city for all 30 MLB parks
# Use exact names as returned by statsapi.mlb.com; None = dome/retractable (skip weather)
VENUE_CITY = {
    # AL East
    "Yankee Stadium":                       "New York",
    "Fenway Park":                          "Boston",
    "Oriole Park at Camden Yards":          "Baltimore",
    "Camden Yards":                         "Baltimore",   # alt name
    "Tropicana Field":                      None,          # dome
    "Rogers Centre":                        None,          # dome
    # AL Central
    "Guaranteed Rate Field":                "Chicago",
    "Progressive Field":                    "Cleveland",
    "Comerica Park":                        "Detroit",
    "Kauffman Stadium":                     "Kansas City",
    "Target Field":                         "Minneapolis",
    # AL West
    "Minute Maid Park":                     None,          # retractable
    "Daikin Park":                          None,          # retractable (new name for Minute Maid)
    "Globe Life Field":                     None,          # dome
    "Angel Stadium":                        "Anaheim",
    "Oakland Coliseum":                     "Oakland",
    "Sutter Health Park":                   "West Sacramento",
    "T-Mobile Park":                        "Seattle",     # retractable but usually open
    # NL East
    "Wrigley Field":                        "Chicago",
    "Great American Ball Park":             "Cincinnati",
    "American Family Field":                None,          # retractable
    "PNC Park":                             "Pittsburgh",
    "Busch Stadium":                        "St. Louis",
    # NL Central
    "Truist Park":                          "Atlanta",
    "loanDepot park":                       None,          # retractable
    "LoanDepot Park":                       None,
    "Nationals Park":                       "Washington DC",
    "Citizens Bank Park":                   "Philadelphia",
    "Citi Field":                           "New York",
    # NL West
    "Coors Field":                          "Denver",
    "Chase Field":                          None,          # retractable
    "Petco Park":                           "San Diego",
    "Dodger Stadium":                       "Los Angeles",
    "UNIQLO Field at Dodger Stadium":       "Los Angeles",  # naming rights variant
    "Oracle Park":                          "San Francisco",
}


def fetch_weather_wttr(slate: list) -> dict:
    """Fetch per-game weather from wttr.in JSON API using venue→city lookup."""
    import urllib.parse
    weather = {}
    seen_venues = set()

    for game in slate:
        venue = game.get("venue", "")
        if not venue or venue in seen_venues:
            continue
        seen_venues.add(venue)

        city = VENUE_CITY.get(venue)
        if city is None:
            weather[venue] = {"dome": True, "conditions": "Domed/Retractable Stadium"}
            continue

        try:
            url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
            data = json.loads(get(url, timeout=15))
            cur = data.get("current_condition", [{}])[0]
            # Also try to get forecast for game time (use next hour if available)
            def _int(v, default=0):
                try:
                    return int(float(v or default))
                except (TypeError, ValueError):
                    return default

            weather[venue] = {
                "city": city,
                "temp_f":     _int(cur.get("temp_F")),
                "conditions": (cur.get("weatherDesc") or [{}])[0].get("value", ""),
                "wind_mph":   _int(cur.get("windspeedMiles")),
                "wind_dir":   cur.get("winddir16Point", ""),
                "precip_pct": round(float(cur.get("precipMM") or 0)),
                "humidity":   _int(cur.get("humidity")),
                "feels_like_f": _int(cur.get("FeelsLikeF")),
            }
        except Exception as e:
            weather[venue] = {"city": city, "error": str(e)}

    return weather


# ---------------------------------------------------------------------------
# LINEUPS  (rotowire — HTML, partially works)
# ---------------------------------------------------------------------------

def fetch_lineups() -> dict:
    html = get("https://www.rotowire.com/baseball/daily-lineups.php")
    soup = BeautifulSoup(html, "html.parser")
    lineups = {}

    for lineup_box in soup.select(
        ".lineup__box, [class*='lineup-box'], [class*='lineupBox']"
    ):
        try:
            teams = lineup_box.select(".lineup__team, [class*='lineup__team']")
            if len(teams) < 2:
                continue
            away_name = teams[0].get_text(strip=True)
            home_name = teams[1].get_text(strip=True)
            key = f"{away_name} vs {home_name}"

            sps = lineup_box.select(".lineup__pitcher, [class*='lineup__pitcher']")
            sp_away = sps[0].get_text(strip=True) if sps else "TBD"
            sp_home = sps[1].get_text(strip=True) if len(sps) > 1 else "TBD"

            away_batters, home_batters = [], []
            for col in lineup_box.select(".lineup__list, [class*='lineup__list']"):
                batters = [
                    li.get_text(strip=True)
                    for li in col.select("li, [class*='batter']")
                ]
                if not away_batters:
                    away_batters = batters
                else:
                    home_batters = batters

            lineups[key] = {
                "sp_away": sp_away,
                "sp_home": sp_home,
                "away_batters": away_batters,
                "home_batters": home_batters,
            }
        except Exception:
            pass

    return lineups


# ---------------------------------------------------------------------------
# ODDS, EVERY BOOK  (The Odds API — needs the ODDS_API_KEY secret)
# ---------------------------------------------------------------------------

# Bookmaker keys as The Odds API spells them. Set the BOOKS repository
# variable to the books you actually hold accounts with; a best price at a
# book you can't use is worth nothing.
DEFAULT_BOOKS = "draftkings,fanduel,betmgm,williamhill_us,espnbet,fanatics,betrivers,ballybet"


def fetch_odds_api() -> dict:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        print("  ODDS_API_KEY not set - skipping (covers.com odds still run)")
        return {}
    books = (os.environ.get("BOOKS") or DEFAULT_BOOKS).replace(" ", "")
    # h2h only, and at most 10 books, so each call costs exactly 1 credit.
    url = (
        "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/"
        f"?apiKey={key}&markets=h2h&oddsFormat=american&bookmakers={books}"
    )
    r = SESSION.get(url, timeout=25)
    r.raise_for_status()
    events = {}
    for ev in r.json():
        away, home = ev.get("away_team"), ev.get("home_team")
        prices = {}
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                o = {x.get("name"): x.get("price") for x in mk.get("outcomes", [])}
                if isinstance(o.get(away), (int, float)) and isinstance(o.get(home), (int, float)):
                    prices[bk["key"]] = {"away": int(o[away]), "home": int(o[home])}
        if not prices:
            continue
        # No-vig probability per book, averaged: the market's fair line.
        fair_away = sum(
            _implied(p["away"]) / (_implied(p["away"]) + _implied(p["home"]))
            for p in prices.values()
        ) / len(prices)
        best_away = max(prices, key=lambda b: prices[b]["away"])
        best_home = max(prices, key=lambda b: prices[b]["home"])
        events[ev.get("id")] = {
            "away_team": away,
            "home_team": home,
            "commence_time": ev.get("commence_time"),
            "best_away": prices[best_away]["away"],
            "best_away_book": best_away,
            "best_home": prices[best_home]["home"],
            "best_home_book": best_home,
            "fair_away": round(fair_away, 4),
            "fair_home": round(1 - fair_away, 4),
            "books": prices,
        }
    remaining = r.headers.get("x-requests-remaining")
    print(f"  odds-api: {len(events)} events, {remaining} credits left")
    return {"events": events, "credits_remaining": remaining, "books_requested": books}


def _same_team(slate_name: str, slate_nick: str, odds_name: str) -> bool:
    return bool(odds_name) and (odds_name == slate_name
                                or (slate_nick and odds_name.endswith(slate_nick)))


def attach_odds(slate: list, odds_api: dict) -> None:
    for gm in slate:
        t0 = gm.get("game_time_utc")
        for ev in (odds_api or {}).get("events", {}).values():
            if not (_same_team(gm["away_team"], gm.get("away_nick"), ev["away_team"])
                    and _same_team(gm["home_team"], gm.get("home_nick"), ev["home_team"])):
                continue
            # Doubleheaders list the same teams twice: match on start time too.
            if t0 and ev.get("commence_time"):
                a = datetime.fromisoformat(t0.replace("Z", "+00:00"))
                b = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
                if abs((a - b).total_seconds()) > 4 * 3600:
                    continue
            gm["odds"] = {k: v for k, v in ev.items() if k not in ("away_team", "home_team")}
            break


# ---------------------------------------------------------------------------
# TEAM BATTING SPLITS vs RHP / LHP  (statsapi.mlb.com)
# ---------------------------------------------------------------------------

def fetch_team_splits(year: str) -> dict:
    url = (
        "https://statsapi.mlb.com/api/v1/teams/stats?stats=statSplits&group=hitting"
        f"&season={year}&sitCodes=vr,vl&leagueIds=103,104"
    )
    data = SESSION.get(url, timeout=20).json()
    out = {}
    for block in data.get("stats", []):
        for s in block.get("splits", []):
            team = s.get("team", {}).get("name")
            side = {"vr": "vs_RHP", "vl": "vs_LHP"}.get(s.get("split", {}).get("code"))
            st = s.get("stat", {})
            pa = st.get("plateAppearances") or 0
            if team and side:
                out.setdefault(team, {})[side] = {
                    "ops": st.get("ops"),
                    "k_pct": round((st.get("strikeOuts") or 0) / pa, 3) if pa else None,
                    "pa": pa,
                }
    return out


# ---------------------------------------------------------------------------
# BULLPEN USAGE, LAST 3 DAYS  (statsapi.mlb.com boxscores)
# ---------------------------------------------------------------------------

def fetch_bullpen(d: str, slate: list) -> dict:
    day = date.fromisoformat(d)
    yday, day_before = (day - timedelta(days=1)).isoformat(), (day - timedelta(days=2)).isoformat()
    sched = SESSION.get(
        "https://statsapi.mlb.com/api/v1/schedule?sportId=1&gameType=R,F,D,L,W"
        f"&startDate={(day - timedelta(days=3)).isoformat()}&endDate={yday}",
        timeout=20,
    ).json()
    wanted = {gm[k] for gm in slate for k in ("away_team", "home_team")}
    usage = {}
    for dd in sched.get("dates", []):
        for g in dd.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            if not {g["teams"][s]["team"]["name"] for s in ("away", "home")} & wanted:
                continue
            box = SESSION.get(
                f"https://statsapi.mlb.com/api/v1/game/{g['gamePk']}/boxscore", timeout=20
            ).json()
            for side in ("away", "home"):
                t = box["teams"][side]
                team = t["team"]["name"]
                if team not in wanted:
                    continue
                u = usage.setdefault(team, {"outs": 0, "days": {}})
                # pitchers[] is in order of appearance; the first is the starter.
                for pid in t.get("pitchers", [])[1:]:
                    p = t.get("players", {}).get(f"ID{pid}", {})
                    st = p.get("stats", {}).get("pitching", {})
                    u["outs"] += _ip_to_outs(st.get("inningsPitched"))
                    name = p.get("person", {}).get("fullName", str(pid))
                    u["days"].setdefault(dd["date"], {})[name] = st.get("numberOfPitches") or 0
    out = {}
    for team, u in usage.items():
        y, b = u["days"].get(yday, {}), u["days"].get(day_before, {})
        out[team] = {
            "relief_ip_last3": f"{u['outs'] // 3}.{u['outs'] % 3}",
            "pitched_yesterday": sorted(y),
            "pitched_back_to_back": sorted(set(y) & set(b)),
            "25plus_pitches_yesterday": sorted(n for n, pc in y.items() if pc >= 25),
        }
    return out


# ---------------------------------------------------------------------------
# WEATHER AT FIRST PITCH  (open-meteo.com — hourly forecast, no key)
# ---------------------------------------------------------------------------

def fetch_weather_first_pitch(slate: list) -> dict:
    """Forecast for the hour each outdoor game starts, keyed by game_id.

    wttr.in above reports conditions at fetch time, which for a bundle built
    in the morning says little about a 7pm first pitch, and its precip field is
    millimetres, not a probability. This gives the rain probability the
    routines' >40% skip rule actually needs.
    """
    out = {}
    geo_cache = {}
    for gm in slate:
        gid = str(gm.get("game_id"))
        venue = gm.get("venue", "")
        if venue in VENUE_CITY and VENUE_CITY[venue] is None:
            out[gid] = {"dome": True}
            continue
        lat, lon = gm.get("venue_lat"), gm.get("venue_lon")
        if lat is None or lon is None:
            city = VENUE_CITY.get(venue)
            if not city:
                continue
            if city not in geo_cache:
                q = urllib.parse.quote(city.replace(" DC", ""))
                res = SESSION.get(
                    f"https://geocoding-api.open-meteo.com/v1/search?count=1&name={q}",
                    timeout=15,
                ).json().get("results") or [{}]
                geo_cache[city] = (res[0].get("latitude"), res[0].get("longitude"))
            lat, lon = geo_cache[city]
        t = gm.get("game_time_utc")
        if lat is None or lon is None or not t:
            continue
        start = datetime.fromisoformat(t.replace("Z", "+00:00"))
        try:
            hourly = SESSION.get(
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}&timezone=UTC"
                "&hourly=temperature_2m,precipitation_probability,wind_speed_10m,wind_direction_10m"
                "&temperature_unit=fahrenheit&wind_speed_unit=mph"
                f"&start_date={start.date().isoformat()}"
                f"&end_date={(start + timedelta(days=1)).date().isoformat()}",
                timeout=15,
            ).json().get("hourly", {})
            times = hourly.get("time", [])
            if not times:
                continue
            target = start.replace(minute=0, second=0, tzinfo=None)
            i = min(range(len(times)),
                    key=lambda k: abs((datetime.fromisoformat(times[k]) - target).total_seconds()))
            out[gid] = {
                "hour_utc": times[i],
                "temp_f": hourly.get("temperature_2m", [None])[i],
                "precip_prob": hourly.get("precipitation_probability", [None])[i],
                "wind_mph": hourly.get("wind_speed_10m", [None])[i],
                "wind_from_deg": hourly.get("wind_direction_10m", [None])[i],
            }
        except Exception as e:
            out[gid] = {"error": str(e)}
    return out


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()

    d = args.date
    year = d[:4]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    bundle = {
        "date": d,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "github-actions-prefetch",
        # "schedule", or the line a routine pushed to requests/data.txt
        "requested_by": os.environ.get("REQUESTED_BY", "schedule"),
    }

    # Fetch slate first (weather needs it for venue list)
    print("[slate] fetching...", flush=True)
    try:
        bundle["slate"] = fetch_slate(d)
        print(f"[slate] OK — {len(bundle['slate'])} games")
    except Exception as e:
        print(f"[slate] FAILED: {e}")
        bundle["slate"] = []
        bundle["slate_error"] = str(e)

    steps = [
        ("standings", lambda: fetch_standings(year)),
        ("sp_stats",  lambda: fetch_sp_stats(year)),
        ("team_splits", lambda: fetch_team_splits(year)),
        ("odds",      fetch_odds_playwright),
        ("odds_api",  fetch_odds_api),
        ("weather",   lambda: fetch_weather_wttr(bundle.get("slate", []))),
        ("weather_first_pitch", lambda: fetch_weather_first_pitch(bundle.get("slate", []))),
        ("lineups",   fetch_lineups),
        ("bullpen",   lambda: fetch_bullpen(d, bundle.get("slate", []))),
    ]

    for key, fn in steps:
        print(f"[{key}] fetching...", flush=True)
        try:
            result = fn()
            bundle[key] = result
            n = len(result)
            print(f"[{key}] OK — {n} items")
        except Exception as e:
            print(f"[{key}] FAILED: {e}")
            bundle[key] = {}
            bundle[f"{key}_error"] = str(e)

    # Put each game's odds, bullpen and first-pitch weather on the game itself.
    slate = bundle.get("slate", [])
    attach_odds(slate, bundle.get("odds_api"))
    for gm in slate:
        gm["bullpen_away"] = bundle.get("bullpen", {}).get(gm["away_team"])
        gm["bullpen_home"] = bundle.get("bullpen", {}).get(gm["home_team"])
        wx = bundle.get("weather_first_pitch", {}).get(str(gm.get("game_id")))
        if wx:
            gm["weather_first_pitch"] = wx

    out_path = out / f"{d}.json"
    out_path.write_text(json.dumps(bundle, indent=2))
    print(f"\nWrote {out_path} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

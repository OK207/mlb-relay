#!/usr/bin/env python3
"""
fetch_daily_data.py — Pre-fetch MLB daily data bundle for the CCR agent.
Runs in GitHub Actions where all sports domains are accessible.
Writes data/YYYY-MM-DD.json to the relay repo.

Sources:
  - Slate + SPs + Standings:  statsapi.mlb.com  (JSON — always works)
  - SP stats:                  baseballsavant.mlb.com CSV  (+ MLB Stats API fallback)
  - Odds + SP context:         covers.com  (Playwright — JS-rendered)
  - Weather:                   wttr.in JSON per venue  (no JS needed)
  - Lineups:                   rotowire.com  (requests — HTML partially works)
"""
import argparse, csv, io, json, re, sys
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

def fetch_slate(d: str) -> list:
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={d}&hydrate=probablePitcher,venue,team&gameType=R,F,D,L,W"
    )
    data = SESSION.get(url, timeout=20).json()
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

            games.append({
                "game_id": g.get("gamePk"),
                "time_et": time_et,
                "away_team": at.get("team", {}).get("name", "?"),
                "home_team": ht.get("team", {}).get("name", "?"),
                "venue": g.get("venue", {}).get("name", ""),
                "status": g.get("status", {}).get("detailedState", ""),
                "sp_away": sp(at),
                "sp_home": sp(ht),
            })
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

                    if not away_mls or not home_mls:
                        continue

                    key = f"{away_abbr} vs {home_abbr}"
                    odds[key] = {
                        "away_abbr": away_abbr,
                        "home_abbr": home_abbr,
                        "away_ml":   away_mls[0],
                        "home_ml":   home_mls[0],
                        "away_ml_best": max(away_mls),
                        "home_ml_best": max(home_mls),
                        "away_sp": {"name": away_sp, "throws": away_hand, "era": away_era},
                        "home_sp": {"name": home_sp, "throws": home_hand, "era": home_era},
                        "books_count": len(away_mls),
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
        ("odds",      fetch_odds_playwright),
        ("weather",   lambda: fetch_weather_wttr(bundle.get("slate", []))),
        ("lineups",   fetch_lineups),
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

    out_path = out / f"{d}.json"
    out_path.write_text(json.dumps(bundle, indent=2))
    print(f"\nWrote {out_path} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

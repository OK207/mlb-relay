#!/usr/bin/env python3
"""
fetch_daily_data.py — Pre-fetch MLB daily data bundle for the CCR agent.

Runs in GitHub Actions where all sports domains are accessible.
Writes data/YYYY-MM-DD.json to the relay repo.

Sources:
  - Slate + probable pitchers: statsapi.mlb.com (JSON, reliable)
  - Standings:                 statsapi.mlb.com (JSON, reliable)
  - SP stats:                  baseballsavant.mlb.com (CSV, reliable)
  - Odds:                      covers.com (HTML parse, best-effort)
  - Weather:                   rotowire.com (HTML parse, best-effort)
  - Lineups:                   rotowire.com (HTML parse, best-effort)
"""
import argparse, csv, io, json, re, sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing deps — run: pip install requests beautifulsoup4")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})


def get(url, timeout=25, **kwargs):
    r = SESSION.get(url, timeout=timeout, **kwargs)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# SLATE + PROBABLE PITCHERS  (statsapi.mlb.com — clean JSON)
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
# STANDINGS  (statsapi.mlb.com — clean JSON)
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
# SP STATS  (baseballsavant.mlb.com CSV — reliable)
# ---------------------------------------------------------------------------

def fetch_sp_stats(year: str) -> dict:
    url = (
        f"https://baseballsavant.mlb.com/leaderboard/custom"
        f"?year={year}&type=pitcher&filter=&sort=4&order=desc"
        f"&min=5&selections=p_era,xera,k_percent,bb_percent,p_formatted_ip&csv=true"
    )
    text = get(url, headers={"Accept": "text/csv"})
    reader = csv.DictReader(io.StringIO(text))
    stats = {}
    for row in reader:
        name = row.get("last_name, first_name", "")
        if "," in name:
            last, first = name.split(",", 1)
            name = f"{first.strip()} {last.strip()}"
        if not name:
            continue
        stats[name] = {
            "era": row.get("p_era", ""),
            "xera": row.get("xera", ""),
            "k_pct": row.get("k_percent", ""),
            "bb_pct": row.get("bb_percent", ""),
            "ip": row.get("p_formatted_ip", ""),
        }
    return stats


# ---------------------------------------------------------------------------
# ODDS  (covers.com — HTML parse, best-effort)
# ---------------------------------------------------------------------------

def fetch_odds() -> dict:
    html = get("https://www.covers.com/sport/baseball/mlb/odds")
    soup = BeautifulSoup(html, "html.parser")
    odds = {}

    # Strategy 1: embedded JSON in <script> tags
    for script in soup.find_all("script"):
        text = script.string or ""
        if not ("moneyLine" in text or "runLine" in text or "gameTotal" in text):
            continue
        for pattern in [
            r'window\.__(?:DATA|data|STATE|state)__?\s*=\s*({.+?})\s*;',
            r'var\s+(?:data|gameData|oddsData)\s*=\s*({.+?})\s*;',
        ]:
            m = re.search(pattern, text, re.DOTALL)
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
                for game in data.get("games", data.get("events", [])):
                    away = (game.get("awayTeam") or game.get("away") or {})
                    home = (game.get("homeTeam") or game.get("home") or {})
                    away_name = away.get("shortName", away.get("name", "?"))
                    home_name = home.get("shortName", home.get("name", "?"))
                    key = f"{away_name} vs {home_name}"
                    odds[key] = {
                        "away_ml": game.get("awayMoneyLine", game.get("awayML")),
                        "home_ml": game.get("homeMoneyLine", game.get("homeML")),
                        "total": game.get("gameTotal", game.get("total")),
                        "over_odds": game.get("overOdds"),
                        "under_odds": game.get("underOdds"),
                        "away_rl": game.get("awayRunLine", game.get("awayRL")),
                        "home_rl": game.get("homeRunLine", game.get("homeRL")),
                    }
                if odds:
                    return odds
            except Exception:
                continue

    # Strategy 2: HTML table/row parsing — covers.com game boxes
    # Each matchup is in a container; away/home rows each have an ML cell
    pairs = []
    team_name = None
    ml_val = None
    for el in soup.select(
        ".cmg_matchup_game_box, [class*='covers-CoversOdds-'], "
        "[class*='game-box'], [class*='matchup']"
    ):
        rows = el.find_all("tr") or [el]
        row_data = []
        for row in rows:
            cells = row.find_all("td")
            if not cells:
                continue
            texts = [c.get_text(strip=True) for c in cells]
            name = texts[0] if texts else ""
            ml_text = next((t for t in texts[1:] if re.match(r'^[+-]?\d{3,4}$', t)), None)
            if name and ml_text:
                row_data.append({"team": name, "ml": int(ml_text)})
        if len(row_data) == 2:
            pairs.append(row_data)

    for pair in pairs:
        key = f"{pair[0]['team']} vs {pair[1]['team']}"
        odds[key] = {"away_ml": pair[0]["ml"], "home_ml": pair[1]["ml"]}

    return odds


# ---------------------------------------------------------------------------
# WEATHER  (rotowire — HTML parse, best-effort)
# ---------------------------------------------------------------------------

def fetch_weather() -> dict:
    html = get("https://www.rotowire.com/baseball/weather.php")
    soup = BeautifulSoup(html, "html.parser")
    weather = {}

    # rotowire weather typically in .weather-forecast containers or tables
    for container in soup.select(
        ".weather-forecast, .weather-box, [class*='WeatherForecast'], "
        "[class*='weather-card'], [class*='weather_card']"
    ):
        try:
            venue_el = container.select_one(
                "[class*='venue'], [class*='stadium'], [class*='ballpark'], "
                "h3, h4, .location"
            )
            temp_el = container.select_one("[class*='temp']")
            wind_el = container.select_one("[class*='wind']")
            cond_el = container.select_one("[class*='cond'], [class*='sky'], [class*='weather']")

            venue = venue_el.get_text(strip=True) if venue_el else None
            if venue:
                weather[venue] = {
                    "temp": temp_el.get_text(strip=True) if temp_el else "",
                    "wind": wind_el.get_text(strip=True) if wind_el else "",
                    "conditions": cond_el.get_text(strip=True) if cond_el else "",
                }
        except Exception:
            pass

    # Fallback: table rows containing temperature pattern
    if not weather:
        for row in soup.select("tr"):
            cells = row.find_all("td")
            texts = [c.get_text(strip=True) for c in cells]
            if len(texts) >= 3 and any(re.search(r'\d+\s*°', t) for t in texts):
                venue = texts[0]
                if venue and len(venue) > 3:
                    weather[venue] = {"raw": " | ".join(t for t in texts if t)}

    return weather


# ---------------------------------------------------------------------------
# LINEUPS  (rotowire — HTML parse, best-effort)
# ---------------------------------------------------------------------------

def fetch_lineups() -> dict:
    html = get("https://www.rotowire.com/baseball/daily-lineups.php")
    soup = BeautifulSoup(html, "html.parser")
    lineups = {}

    for lineup_box in soup.select(
        ".lineup__box, [class*='lineup-box'], [class*='lineupBox']"
    ):
        try:
            # Team names
            teams = lineup_box.select(".lineup__team, [class*='lineup__team']")
            if len(teams) < 2:
                continue
            away_name = teams[0].get_text(strip=True)
            home_name = teams[1].get_text(strip=True)
            key = f"{away_name} vs {home_name}"

            # SPs
            sps = lineup_box.select(".lineup__pitcher, [class*='lineup__pitcher']")
            sp_away = sps[0].get_text(strip=True) if sps else "TBD"
            sp_home = sps[1].get_text(strip=True) if len(sps) > 1 else "TBD"

            # Batters
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
    parser = argparse.ArgumentParser(description="Fetch MLB daily data bundle")
    parser.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--out-dir", default="data", help="Output directory")
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

    steps = [
        ("slate",      lambda: fetch_slate(d)),
        ("standings",  lambda: fetch_standings(year)),
        ("sp_stats",   lambda: fetch_sp_stats(year)),
        ("odds",       fetch_odds),
        ("weather",    fetch_weather),
        ("lineups",    fetch_lineups),
    ]

    for key, fn in steps:
        print(f"[{key}] fetching...", flush=True)
        try:
            result = fn()
            bundle[key] = result
            n = len(result) if hasattr(result, "__len__") else "?"
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

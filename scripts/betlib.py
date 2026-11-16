#!/usr/bin/env python3
"""Shared helpers for the picks routines. Standard library only.

Everything that is arithmetic or bookkeeping lives in scripts/ so a routine
never does it in its head: prices, fair lines, edges, stakes, grading, file
names and the git push are all computed here.
"""
import datetime as dt
import difflib
import json
import os
import re
import statistics
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

SPORTS = {
    "mlb": {"odds_key": "baseball_mlb", "espn": "baseball/mlb", "picks": "picks",
            "grades": "grades", "tag": "", "label": "MLB"},
    "nba": {"odds_key": "basketball_nba", "espn": "basketball/nba", "picks": "picks/nba",
            "grades": "grades/nba", "tag": "-nba", "label": "NBA"},
    "cbb": {"odds_key": "basketball_ncaab", "espn": "basketball/mens-college-basketball",
            "picks": "picks/cbb", "grades": "grades/cbb", "tag": "-cbb", "label": "CBB"},
    "ufc": {"odds_key": "mma_mixed_martial_arts", "espn": "mma/ufc", "picks": "picks/ufc",
            "grades": "picks/ufc/grades", "tag": "-ufc", "label": "UFC"},
}

BOOK_NAMES = {
    "draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
    "williamhill_us": "Caesars", "espnbet": "ESPN BET", "fanatics": "Fanatics",
    "betrivers": "BetRivers", "ballybet": "Bally Bet", "bovada": "Bovada",
    "betonlineag": "BetOnline", "lowvig": "LowVig", "mybookieag": "MyBookie",
    "betus": "BetUS", "hardrockbet": "Hard Rock",
}


# --------------------------------------------------------------------------
# config, dates, files
# --------------------------------------------------------------------------

def config() -> dict:
    return json.loads((ROOT / "config" / "betting.json").read_text())


def rules(sport: str) -> dict:
    return config()["sports"][sport]


def my_books() -> list:
    env = os.environ.get("BOOKS", "").replace(" ", "")
    return [b for b in env.split(",") if b] or config()["books"]


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC)


def today_et() -> str:
    return dt.datetime.now(ET).date().isoformat()


def parse_time(s: str) -> dt.datetime:
    s = s.replace("Z", "+00:00")
    if re.search(r"T\d\d:\d\d[+-]", s):          # ESPN drops the seconds
        s = s[:16] + ":00" + s[16:]
    return dt.datetime.fromisoformat(s)


def et_date(s: str) -> str:
    return parse_time(s).astimezone(ET).date().isoformat()


def et_clock(s: str) -> str:
    t = parse_time(s).astimezone(ET)
    return t.strftime("%a %-I:%M %p ET")


def pretty_date(d: str) -> str:
    return dt.date.fromisoformat(d).strftime("%b %-d")


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def write_json(path, obj) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def unwrap(doc) -> list:
    """UFC pick files are {"event":..., "picks":[...]}; the rest are a list."""
    if isinstance(doc, dict):
        return doc.get("picks", [])
    return doc or []


def picks_path(sport: str, d: str) -> Path:
    return ROOT / SPORTS[sport]["picks"] / f"{d}.json"


def grades_path(sport: str, d: str) -> Path:
    return ROOT / SPORTS[sport]["grades"] / f"{d}.json"


def lines_path(sport: str, d: str) -> Path:
    return ROOT / "lines" / sport / f"{d}.json"


def pick_dates(sport: str) -> list:
    folder = ROOT / SPORTS[sport]["picks"]
    return sorted(p.stem for p in folder.glob("20??-??-??.json"))


# --------------------------------------------------------------------------
# odds arithmetic
# --------------------------------------------------------------------------

def implied(odds) -> float:
    """Break-even win probability of an American price, vig included."""
    odds = float(odds)
    return -odds / (-odds + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def profit(odds, units) -> float:
    """What a winning bet pays on top of the stake. Never includes the stake."""
    odds, units = float(odds), float(units)
    return round(units * (100.0 / -odds if odds < 0 else odds / 100.0), 2)


def fmt_odds(odds) -> str:
    odds = int(round(float(odds)))
    return f"+{odds}" if odds > 0 else str(odds)


def fmt_units(u) -> str:
    return f"{float(u):.2f}".rstrip("0").rstrip(".")


def stake_for(edge_pts: float, r: dict) -> float:
    for min_edge, units in r["tiers"]:
        if edge_pts >= min_edge:
            scaled = units * float(r.get("stake_scale", 1.0))
            return round(scaled * 4) / 4.0
    return -1.0                                   # below every tier: no bet


def book_name(key: str) -> str:
    return BOOK_NAMES.get(key, key)


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------

class Blocked(Exception):
    """The environment's network policy refused the host."""


def http_get(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read()
        if body[:2] == b"\x1f\x8b":
            import gzip
            body = gzip.decompress(body)
        body = body[:300].decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} from {url.split('?')[0]}: {body}") from None
    except urllib.error.URLError as e:
        msg = str(e.reason)
        if "403" in msg or "Tunnel" in msg or "tunnel" in msg:
            host = url.split("/")[2]
            raise Blocked(f"{host} is not on this environment's allowed hosts") from None
        raise RuntimeError(f"{url.split('?')[0]}: {msg}") from None


def http_json(url: str, timeout: int = 25):
    body, _ = http_get(url, timeout)
    return json.loads(body)


def espn_scoreboard(sport: str, d: str) -> list:
    """Events for one ET date 'YYYY-MM-DD', or every date in 'YYYYMMDD-YYYYMMDD',
    from ESPN's public API."""
    base = (f"https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport]['espn']}"
            f"/scoreboard?limit=400" + ("&groups=50" if sport == "cbb" else ""))
    q = d.replace("-", "") if len(d) == 10 else d
    if "-" not in q or sport == "ufc":             # UFC takes a range; team sports do not
        return http_json(f"{base}&dates={q}").get("events", [])
    a, b = (dt.datetime.strptime(x, "%Y%m%d").date() for x in q.split("-"))
    events, seen = [], set()
    while a <= b:
        for ev in http_json(f"{base}&dates={a:%Y%m%d}").get("events", []):
            if ev["id"] not in seen:
                seen.add(ev["id"])
                events.append(ev)
        a += dt.timedelta(days=1)
    return events


# --------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ").replace("st.", "st").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"(?<=\w) st\b", " state", s)      # "Long Beach St" = "Long Beach State"


def name_score(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = a.split(), b.split()
    if ta == tb[:len(ta)] or tb == ta[:len(tb)]:  # "duke" vs "duke blue devils"
        return 0.93
    if ta[-len(tb):] == tb or tb[-len(ta):] == ta:  # "lakers" vs "los angeles lakers"
        return 0.93
    return difflib.SequenceMatcher(None, a, b).ratio()


NBA_NICK = {"Portland Trail Blazers": "Blazers"}


def short_name(sport: str, full: str) -> str:
    """The name a bet is logged under."""
    if sport in ("nba", "mlb"):
        if full in NBA_NICK:
            return NBA_NICK[full]
        two = ("Red Sox", "White Sox", "Blue Jays")
        for t in two:
            if full.endswith(t):
                return t
        if full.endswith("Athletics"):
            return "A's"
        return full.split()[-1]
    if sport == "ufc":
        return full.split()[-1]
    return full


def bet_key(bet: str) -> str:
    """Compare bets on the leading clause, as the sheet workflows do."""
    return re.sub(r"\s+", " ", str(bet).split(" vs ")[0].split(" - ")[0].strip().lower())


# --------------------------------------------------------------------------
# the market
# --------------------------------------------------------------------------

def median(xs):
    return statistics.median(xs) if xs else None


def fair_two_way(pairs) -> float:
    """No-vig probability of side A: each book's two prices with the vig taken
    out, then the median across books. pairs = [(price_a, price_b), ...]."""
    probs = []
    for a, b in pairs:
        ia, ib = implied(a), implied(b)
        if 1.0 <= ia + ib <= 1.15:                # a real two-way market
            probs.append(ia / (ia + ib))
    return median(probs)


def record_line(sport: str) -> str:
    """One line for the foot of a text: the record since the current rules."""
    since = config().get("rules_from", "2026-01-01")
    w = l = p = 0
    net = staked = 0.0
    for d in pick_dates(sport):
        if d < since:
            continue
        for g in unwrap(read_json(grades_path(sport, d), [])):
            o = g.get("outcome")
            if o not in ("W", "L", "P"):
                continue
            w, l, p = w + (o == "W"), l + (o == "L"), p + (o == "P")
            net += float(g.get("net") or 0)
            staked += float(g.get("units") or 0)
    clv = []
    for f in sorted((ROOT / "clv" / sport).glob("20??-??-??.json")):
        if f.stem >= since:
            clv += [c["clv_pts"] for c in read_json(f, {}).get("picks", [])
                    if c.get("clv_pts") is not None]
    out = f"{SPORTS[sport]['label']} since {pretty_date(since)}: {w}-{l}" + (f"-{p}" if p else "")
    out += f", {net:+.2f}u"
    if staked:
        out += f" ({100 * net / staked:+.0f}% ROI)"
    if clv:
        out += f" | line value {sum(clv) / len(clv):+.1f} pts avg over {len(clv)} bets"
    return out

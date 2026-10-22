#!/usr/bin/env python3
"""
game_sheet.py — print a data bundle as one block per game, for the routines.

The bundle (data/YYYY-MM-DD.json, built by fetch_daily_data.py) keeps SP
stats, team splits and standings in separate tables keyed by name. Joining
those by hand is where a routine misreads a pitcher or pairs the wrong teams,
so this does the joins once and prints everything about a game together.

    python3 scripts/game_sheet.py /tmp/bundle.json
"""
import json, sys, unicodedata

BOOK_NAMES = {
    "draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
    "williamhill_us": "Caesars", "espnbet": "ESPN BET", "fanatics": "Fanatics",
    "betrivers": "BetRivers", "ballybet": "Bally Bet",
}


def norm(name: str) -> str:
    return unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower().strip()


def side_line(g: dict, side: str, sp_stats: dict, splits: dict, standings: dict) -> str:
    opp = "home" if side == "away" else "away"
    team = g.get(f"{side}_team", "?")
    nick = g.get(f"{side}_nick") or ""
    sp = g.get(f"sp_{side}") or {}
    s = sp_stats.get(norm(sp.get("name")), {})
    season = sp.get("season") or {}
    last3 = sp.get("last3") or {}
    # Standings have been keyed by nickname in some bundles, full name in others.
    rec = standings.get(team) or standings.get(nick) or {}
    opp_hand = (g.get(f"sp_{opp}") or {}).get("throws", "?")
    split = (splits.get(team) or {}).get({"R": "vs_RHP", "L": "vs_LHP"}.get(opp_hand, ""), {})
    pen = g.get(f"bullpen_{side}") or {}
    pct = lambda v: f"{100 * v:.1f}" if isinstance(v, (int, float)) else "?"
    form = (f" | last 3 starts {last3.get('ip')} IP, {last3.get('era')} ERA, {last3.get('k')} K, {last3.get('bb')} BB"
            if last3 else "")
    return (
        f"  {side.upper():<4} {nick or team:<13} {rec.get('wins', '?')}-{rec.get('losses', '?')}"
        f" | SP {sp.get('name', 'TBD')} ({sp.get('throws', '?')})"
        f" ERA {season.get('era') or s.get('era', '?')} xERA {s.get('xera') or '?'}"
        f" K% {pct(season.get('k_pct')) if season else s.get('k_pct') or '?'}"
        f" BB% {pct(season.get('bb_pct')) if season else s.get('bb_pct') or '?'}"
        f" IP {season.get('ip') or s.get('ip', '?')} ({season.get('ip_per_start', '?')} per start){form}"
        f"\n       bats vs {opp_hand}HP: OPS {split.get('ops', '?')} K% {pct(split.get('k_pct'))}"
        f" | pen last 3 days {pen.get('relief_ip_last3', '?')} IP;"
        f" back-to-back: {', '.join(pen.get('pitched_back_to_back') or []) or 'none'};"
        f" 25+ pitches yesterday: {', '.join(pen.get('25plus_pitches_yesterday') or []) or 'none'}"
    )


def main(path: str) -> None:
    try:
        b = json.load(open(path))
    except Exception as e:
        print(f"NO_BUNDLE ({e})")
        return
    slate = b.get("slate") or []
    sp_stats = {norm(k): v for k, v in (b.get("sp_stats") or {}).items()}
    splits = b.get("team_splits") or {}
    standings = b.get("standings") or {}
    oa = b.get("odds_api") or {}
    print(f"BUNDLE {b.get('date')} generated {b.get('generated_at')} "
          f"requested_by={b.get('requested_by', '?')} games={len(slate)}")
    if oa:
        print(f"The Odds API: books {oa.get('books_requested')} | credits left {oa.get('credits_remaining')}")
    for key in [k for k in b if k.endswith("_error")]:
        print(f"  ! {key}: {b[key]}")
    if not slate:
        print("EMPTY SLATE")
        return

    for i, g in enumerate(slate, 1):
        print(f"\n[G{i}] {g.get('away_nick') or g.get('away_team')} @ {g.get('home_nick') or g.get('home_team')}"
              f"  {g.get('time_et', '?')} ET  type={g.get('game_type', '?')}"
              f"{' (' + g['series'] + ')' if g.get('series') and g.get('game_type') != 'R' else ''}"
              f"  status={g.get('status', '?')}  {g.get('venue', '')}"
              f"  HP ump: {g.get('hp_umpire') or 'not posted'}")
        print(side_line(g, "away", sp_stats, splits, standings))
        print(side_line(g, "home", sp_stats, splits, standings))
        o = g.get("odds") or {}
        if o:
            print(f"  ODDS best: {g.get('away_nick')} {o.get('best_away'):+d} at {BOOK_NAMES.get(o.get('best_away_book'), o.get('best_away_book'))}"
                  f" / {g.get('home_nick')} {o.get('best_home'):+d} at {BOOK_NAMES.get(o.get('best_home_book'), o.get('best_home_book'))}"
                  f" | no-vig fair: {o.get('fair_away'):.3f} / {o.get('fair_home'):.3f}")
            print("       by book: " + "; ".join(
                f"{BOOK_NAMES.get(k, k)} {v['away']:+d}/{v['home']:+d}" for k, v in sorted((o.get("books") or {}).items())))
        else:
            print("  ODDS: none from The Odds API for this game - see COVERS ODDS below")
        w = g.get("weather_first_pitch") or {}
        if w.get("dome"):
            print("  WEATHER: dome / roof")
        elif w and "error" not in w:
            print(f"  WEATHER at first pitch: {w.get('temp_f')}F, rain {w.get('precip_prob')}%,"
                  f" wind {w.get('wind_mph')} mph from {w.get('wind_from_deg')} deg")
        else:
            print("  WEATHER: n/a")

    covers = b.get("odds") or {}
    if covers:
        print("\nCOVERS ODDS (first listed book; best = best coherent pair across books):")
        for k, v in covers.items():
            print(f"  {k}: {v.get('away_ml')}/{v.get('home_ml')}"
                  f"  best {v.get('away_ml_best')}/{v.get('home_ml_best')}  books {v.get('books_count')}")
    lineups = b.get("lineups") or {}
    print(f"\nLINEUPS posted for {len(lineups)} game(s):")
    for k, v in lineups.items():
        print(f"  {k}: away {', '.join(v.get('away_batters') or []) or '-'}"
              f" | home {', '.join(v.get('home_batters') or []) or '-'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bundle.json")

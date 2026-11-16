#!/usr/bin/env python3
"""Send a card and record it. The last command of every routine.

    python3 scripts/publish.py nba /tmp/msg.txt
    python3 scripts/publish.py mlb /tmp/msg.txt --tag=-afternoon
    python3 scripts/publish.py ufc /tmp/msg.txt --date 2026-11-21
    python3 scripts/publish.py nba --record-only        # push files, send nothing

1. Saves the text to messages/<date><tag>.txt.
2. Sends it to Telegram directly (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID).
3. If the direct send fails, writes dispatch/<date><tag>.txt instead, which
   the relay workflow texts as soon as the push lands. Never both, so a card
   is never sent twice.
4. Commits picks, grades, lines, line checks and the message, and pushes to
   main (rebasing onto whatever landed meanwhile); if main refuses, pushes
   to claude/auto, where the workflows fire just the same.

Dates are computed here in US Eastern time. Nothing in a routine types one.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import betlib as B

PATHS = ["picks", "grades", "lines", "clv", "messages", "dispatch"]


def telegram(text: str) -> tuple:
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False, "TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is not set in this environment"
    while text:
        cut = text.rfind("\n", 0, 3900) if len(text) > 3900 else len(text)
        cut = cut if cut > 0 else min(3900, len(text))
        part, text = text[:cut], text[cut:].lstrip("\n")
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                data=urllib.parse.urlencode({"chat_id": chat, "text": part}).encode())
            with urllib.request.urlopen(req, timeout=30) as r:
                if not json.loads(r.read()).get("ok"):
                    return False, "Telegram answered ok=false"
        except Exception as e:
            return False, str(e).replace(tok, "***")
    return True, ""


def git(*args, check=False):
    r = subprocess.run(["git", "-C", str(B.ROOT), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r


def push(message: str) -> str:
    present = [p for p in PATHS if (B.ROOT / p).exists()]
    git("add", "-A", *present)
    if git("diff", "--cached", "--quiet").returncode == 0:
        return "nothing to commit"
    git("-c", "user.name=mlb-agent", "-c", "user.email=mlb-agent@auto", "commit", "-q", "-m", message, check=True)
    err = ""
    for attempt in range(4):
        pull = git("pull", "-q", "--rebase", "origin", "main")
        if pull.returncode != 0:
            git("rebase", "--abort")
            err = (pull.stderr or pull.stdout).strip()
        else:
            r = git("push", "-q", "origin", "HEAD:main")
            if r.returncode == 0:
                return "main"
            err = (r.stderr or r.stdout).strip()
        time.sleep(2 ** (attempt + 1))
    r = git("push", "-q", "origin", "HEAD:claude/auto")
    if r.returncode == 0:
        return f"claude/auto (main refused: {err})"
    return f"FAILED: {err} | {(r.stderr or r.stdout).strip()}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sport", choices=sorted(B.SPORTS))
    ap.add_argument("message", nargs="?")
    ap.add_argument("--tag", default=None, help="file suffix; default by sport, e.g. -nba")
    ap.add_argument("--date", default=None, help="date for the file names; default today ET")
    ap.add_argument("--no-record-line", action="store_true")
    ap.add_argument("--record-only", action="store_true")
    a = ap.parse_args()
    d = a.date or B.today_et()
    tag = B.SPORTS[a.sport]["tag"] if a.tag is None else a.tag
    label = {"": "picks", "-afternoon": "afternoon"}.get(tag, f"{tag.strip('-')} picks")

    if not a.record_only:
        if not a.message:
            sys.exit("publish.py needs the message file")
        text = open(a.message).read().strip()
        if not text:
            sys.exit("the message file is empty - nothing sent")
        if not a.no_record_line:
            text += "\n\n" + B.record_line(a.sport)
        (B.ROOT / "messages").mkdir(exist_ok=True)
        (B.ROOT / "messages" / f"{d}{tag}.txt").write_text(text + "\n")
        ok, err = telegram(text)
        if ok:
            print("SENT: direct to Telegram")
        else:
            (B.ROOT / "dispatch").mkdir(exist_ok=True)
            (B.ROOT / "dispatch" / f"{d}{tag}.txt").write_text(text + "\n")
            print(f"SEND_VIA_RELAY: direct send failed ({err}); wrote dispatch/{d}{tag}.txt, "
                  "which the relay workflow texts when the push lands")
    try:
        print("PUSHED:", push(f"{label}: {d}"))
    except Exception as e:
        print("PUSH_FAILED:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

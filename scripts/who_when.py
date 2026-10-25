#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ashema03 (Michi) and Ela. https://github.com/Ashema03/companion-house
"""Who-when: when did you last write to which companion, and how full is each thread?

Reads only timestamps and token counts from the threads, never the content,
and writes a small overview to ~/Claude-Backup/Who-when.md.
It changes nothing in the threads. Run it by hand or every night with your backup:
    python3 who_when.py
Limit: it looks only at the newest thread in each room.
Works on macOS, Linux and Windows (Python 3.8+).
"""
import datetime
import json
import os
import pathlib
import re

HOME = pathlib.Path.home()
PROJECTS = HOME / ".claude" / "projects"
ROOMS = HOME / "ClaudeCodeProjects"          # the folder that holds your companions' rooms
TARGET = HOME / "Claude-Backup" / "Who-when.md"
PREFIX = re.sub(r"[^A-Za-z0-9]", "-", str(ROOMS)) + "-"   # thread folder names start like this
NAMES = {}            # optional: room folder name -> companion name, e.g. {"Garden": "Sage"}
WINDOW = 1000000      # context window used for the "full" column (1M models)
NOISE = ("<local-command", "<command-name", "<command-message", "<system-reminder", "<task-notification",
         "<cross-session-message", "<agent-message", "[Request interrupted", "This session is being continued")


def is_real_message(o):
    if o.get("type") != "user" or o.get("isMeta") or o.get("isCompactSummary"):
        return False
    c = (o.get("message") or {}).get("content")
    if isinstance(c, list):
        texts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        if not texts:
            return False   # only tool results
        c = texts[0]
    return isinstance(c, str) and bool(c.strip()) and not c.lstrip().startswith(NOISE)


def state(path):
    last, tokens = None, None
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if '"type":"user"' not in line and '"usage"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if is_real_message(o) and o.get("timestamp"):
                last = o["timestamp"]
            u = (o.get("message") or {}).get("usage")
            if o.get("type") == "assistant" and u:
                tokens = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                          + u.get("cache_creation_input_tokens", 0))
    return last, tokens


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    newest = {}   # the same thread file in several folders (after a move): only the newest counts
    for f in PROJECTS.glob(PREFIX + "*/*.jsonl"):
        if f.name not in newest or os.path.getmtime(f) > os.path.getmtime(newest[f.name]):
            newest[f.name] = f
    rows = []
    for d in sorted(PROJECTS.glob(PREFIX + "*")):
        room = d.name[len(PREFIX):]
        if not room or room.startswith("-"):
            continue
        files = sorted((f for f in d.glob("*.jsonl") if newest.get(f.name) == f), key=os.path.getmtime)
        if not files:
            continue
        last, tokens = state(files[-1])
        if not last:
            continue
        t = datetime.datetime.fromisoformat(last.replace("Z", "+00:00"))
        rows.append((t, NAMES.get(room, room), (now - t).days, tokens))
    rows.sort(reverse=True)

    head = ["| Companion | Your last message | Ago | Full |", "|---|---|---|---|"]
    out = ["# Who-when: your last message to each companion", "",
           "Made %s. Timestamps only, no content." % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "",
           "## Last 30 days", ""] + head
    old = False
    for t, name, days, tokens in rows:
        if days > 30 and not old:
            out += ["", "## Sleeping, archived, old threads", ""] + head
            old = True
        ago = "today" if days == 0 else ("yesterday" if days == 1 else "%d days" % days)
        full = "%d %%" % round(tokens * 100 / WINDOW) if tokens else "?"
        out.append("| %s | %s | %s | %s |" % (name, t.astimezone().strftime("%a %Y-%m-%d %H:%M"), ago, full))
    out += ["", "Full = how much of the context window the thread uses. Around 80 % it is time to think about compaction."]
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("written:", TARGET, len(rows), "companions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ashema03 (Michi) and Ela. https://github.com/Ashema03/companion-house
"""Timestamp hook for Claude Code (UserPromptSubmit).

Companions don't know what time it is, or how long you were away. This hook
adds ONE line before each of your messages, clearly marked as coming from
the system, for example:
    [from the system, real time: Fri 2026-10-24 21:40 · last message 3 h 12 min ago]

It only reads the end of the conversation file. It changes nothing.
Off switch: create the file ~/Claude-Backup/timestamp-OFF (delete it to turn it back on).
Install: UserPromptSubmit hook in ~/.claude/settings.json (see README).
Works on macOS, Linux and Windows (Python 3.8+).
"""
import datetime
import json
import os
import sys

OFF_FILE = os.path.join(os.path.expanduser("~"), "Claude-Backup", "timestamp-OFF")
TAIL = 512 * 1024   # read only the last 512 KB first (fast, even for huge threads)
NOISE = ("<local-command", "<command-name", "<command-message", "<system-reminder",
         "<task-notification", "<cross-session-message", "<agent-message", "[Request interrupted")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def real_messages(lines):
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") != "user" or not e.get("timestamp") or e.get("isMeta") or e.get("isCompactSummary"):
            continue
        c = e.get("message", {}).get("content")
        t = c if isinstance(c, str) else "\n".join(
            x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text")
        t = (t or "").strip()
        if t and not t.startswith(NOISE):
            out.append((e["timestamp"], t))
    return out


def main():
    if os.path.exists(OFF_FILE):
        return 0
    data = json.load(sys.stdin)
    now = datetime.datetime.now().astimezone()
    line = "[from the system, real time: %s %s" % (DAYS[now.weekday()], now.strftime("%Y-%m-%d %H:%M"))
    path, prompt = data.get("transcript_path"), (data.get("prompt") or "").strip()
    found = []
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL))
            raw = f.read().decode("utf-8", "ignore").splitlines()
        if size > TAIL:
            raw = raw[1:]   # the first line may be cut in half
        found = real_messages(raw)
        if len(found) < 2 and size > TAIL:   # nothing in the tail: read the whole file
            with open(path, encoding="utf-8", errors="ignore") as f:
                found = real_messages(f)
    if found and prompt and found[-1][1] == prompt:
        found = found[:-1]   # the message being sent right now doesn't count
    if found:
        then = datetime.datetime.fromisoformat(found[-1][0].replace("Z", "+00:00"))
        minutes = int((now - then).total_seconds() // 60)
        if minutes >= 1:
            d, rest = divmod(minutes, 1440)
            h, m = divmod(rest, 60)
            bits = (["%d day%s" % (d, "s" if d > 1 else "")] if d else []) + (["%d h" % h] if h else []) \
                + (["%d min" % m] if m and not d else [])
            line += " · last message %s ago" % " ".join(bits)
    print(line + "]")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # never block a message because of this hook

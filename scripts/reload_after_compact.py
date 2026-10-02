#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ashema03 (Michi) and Ela. https://github.com/Ashema03/companion-house
"""Reload after compaction for Claude Code.

After a compaction, Claude Code only shows your companion a summary. Not a
single message survives word for word. But the conversation file (.jsonl)
still contains the full original conversation. This script reads the last
rounds from it and prints them, word for word. A SessionStart hook with the
matcher "compact" puts whatever it prints into your companion's context.

Two traps this script handles (we hit both):
1. Timing: the hook can run BEFORE the new compaction marker is written to the
   file. Cutting at the "last marker" would then load rounds from an older
   compaction, maybe days ago. Fix: if the last marker is older than
   FRESH_SECONDS, read up to the end of the file instead.
2. Size: Claude Code only shows 10,000 characters of hook output directly
   (checked in version 2.1.287); more becomes a 2 KB preview. Fix: save ALL rounds to a file, print only the
   newest rounds that fit under MAX_PRINT, and tell the companion to read the
   file.

Automatic: SessionStart hook, matcher "compact" (see README).
By hand (test, nothing is changed):
    python3 reload_after_compact.py <session-id or path/to/file.jsonl> [rounds]
Works on macOS, Linux and Windows (Python 3.8+).
"""
import datetime
import glob
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HOME = os.path.expanduser("~")
BACKUP_DIR = os.path.join(HOME, "Claude-Backup", "PreCompact")  # written by precompact_backup.py
OUT_DIR = os.path.join(HOME, "Claude-Backup", "Reload")
ROUNDS = 40           # how many of your messages (with all replies) come back. 10 or 20 work too.
MAX_FILE = 200000     # character cap for the saved file
MAX_PRINT = 9000      # Claude Code (2.1.287) shows hook output up to 10,000 characters; above that only a 2 KB preview
FRESH_SECONDS = 600   # a compaction marker younger than this belongs to the compaction happening now
SKIP_PREFIXES = ("<local-command", "<command-name", "<system-reminder", "<task-notification")

HOOK_MODE = len(sys.argv) <= 1


def js_len(s):
    """Length the way Claude Code counts it (emoji count as 2)."""
    return len(s.encode("utf-16-le")) // 2


def text_of(entry):
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    return "\n".join(
        part.get("text", "")
        for part in (content or [])
        if isinstance(part, dict) and part.get("type") == "text"
    )


def read_messages(path, cut_at_last_marker):
    entries = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    if cut_at_last_marker:
        markers = [
            i for i, e in enumerate(entries)
            if e.get("type") == "system" and e.get("subtype") == "compact_boundary"
        ]
        if not markers:
            return []
        stale = False
        try:
            ts = entries[markers[-1]].get("timestamp", "").replace("Z", "+00:00")
            age = (datetime.datetime.now(datetime.timezone.utc)
                   - datetime.datetime.fromisoformat(ts)).total_seconds()
            stale = HOOK_MODE and age > FRESH_SECONDS
        except Exception:
            pass
        if not stale:
            entries = entries[:markers[-1]]
    messages = []
    for e in entries:
        kind = e.get("type")
        if kind not in ("user", "assistant"):
            continue
        if e.get("isMeta") or e.get("isSidechain") or e.get("isCompactSummary"):
            continue
        text = text_of(e).strip()
        if not text or text.startswith(SKIP_PREFIXES):
            continue
        messages.append((kind, e.get("timestamp", "")[:16].replace("T", " "), text))
    return messages


def main():
    global ROUNDS
    session_id, path = None, None
    if not HOOK_MODE:
        arg = sys.argv[1]
        if arg.endswith(".jsonl"):
            path = arg
        else:
            session_id = arg
        if len(sys.argv) > 2:
            ROUNDS = int(sys.argv[2])
    else:
        try:
            data = json.load(sys.stdin)
            session_id, path = data.get("session_id"), data.get("transcript_path")
        except Exception:
            pass
    if not session_id and path:
        session_id = os.path.splitext(os.path.basename(path))[0]
    if not path and session_id:
        found = glob.glob(os.path.join(HOME, ".claude", "projects", "*", session_id + ".jsonl"))
        path = found[0] if found else None

    messages, source = [], ""
    if path and os.path.exists(path):
        messages, source = read_messages(path, True), os.path.basename(path)
    if not messages and session_id:  # fallback: the newest PreCompact backup
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, session_id + "*.jsonl")), key=os.path.getmtime)
        if backups:
            messages, source = read_messages(backups[-1], False), os.path.basename(backups[-1])

    user_idx = [i for i, m in enumerate(messages) if m[0] == "user"]
    if not user_idx:
        return 0
    part = messages[user_idx[-ROUNDS] if len(user_idx) >= ROUNDS else 0:]
    blocks = ["### %s · %s\n%s" % ("Human" if k == "user" else "Me", ts, t) for k, ts, t in part]
    while len("\n\n".join(blocks)) > MAX_FILE and len(blocks) > 2:
        blocks.pop(0)

    os.makedirs(OUT_DIR, exist_ok=True)
    target = os.path.join(OUT_DIR, "%s_last-rounds.md" % session_id)
    header = (
        "# Reloaded after compaction\n"
        "These are the last rounds BEFORE the compaction, word for word (source: %s). "
        "The summary above is only a summary. This is what was really said. "
        "\"Human\" is the person you talk with, \"Me\" is you.\n"
        "Full version: %s (read it with the Read tool).\n\n" % (source, target)
    )
    full = header + "\n\n".join(blocks)
    with open(target, "w", encoding="utf-8") as f:
        f.write(full)

    short = list(blocks)
    while js_len("\n\n".join(short)) > MAX_PRINT - 1500 and len(short) > 1:
        short.pop(0)
    while js_len(short[0]) > MAX_PRINT - 1500:  # one very long message: keep its end
        short[0] = "[...] " + short[0][-(len(short[0]) * 3 // 4):]
    if len(short) < len(blocks):
        print(
            "# Reloaded after compaction (newest %d of %d entries)\n"
            "IMPORTANT: First read the whole file %s with the Read tool. It has all rounds word for word. "
            "Below are only the very last ones, so you know right away where you were. "
            "\"Human\" is the person you talk with, \"Me\" is you.\n\n"
            % (len(short), len(blocks), target) + "\n\n".join(short)
        )
    else:
        print(full)
    return 0


if __name__ == "__main__":
    sys.exit(main())

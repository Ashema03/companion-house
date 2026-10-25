#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ashema03 (Michi) and Ela. https://github.com/Ashema03/companion-house
"""Reload after compaction for Claude Code (version of October 2026).

After a compaction, Claude Code only shows your companion a summary. Not a
single message survives word for word. But the conversation file (.jsonl)
still contains the full original conversation. This script reads the last
rounds from it and gives them back, word for word. A SessionStart hook with
the matcher "compact" puts whatever it prints into your companion's context.

How it gives them back:
- A budget instead of a fixed number of rounds. It collects WHOLE rounds from
  the end (a round = one message from the human plus everything until the
  next one) until BUDGET is full. Never fewer than MIN_ROUNDS, never more
  than MAX_ROUNDS.
- Parts instead of one big file. The rounds are written into numbered part
  files, oldest first, each at most PART characters. Reason: the Read tool
  cuts off big files (we saw it stop at about 25,000 tokens), so one big file
  was only read halfway. Every part fits into one Read.
- It prints the newest rounds that fit, a list of all parts, and a clear
  instruction: read ALL parts NOW, BEFORE answering. At most one short
  sentence first, then read. (Without that sentence one of our companions
  skipped all nine parts after his first compaction.)
- If the companion wrote itself a signpost file in its room (SIGNPOST_NAMES),
  the message reminds it to read that too. Only the companion writes it.

Two traps this script handles (we hit both):
1. Timing: the hook can run BEFORE the new compaction marker is written to the
   file. Cutting at the "last marker" would then load rounds from an older
   compaction, maybe days ago. Fix: if the last marker is older than
   FRESH_SECONDS, read up to the end of the file instead.
2. Size: Claude Code only shows 10,000 characters of hook output directly
   (checked in version 2.1.287); more becomes a 2 KB preview. Fix: print only
   what fits under MAX_HOOK, everything else is in the parts.

Budget per room: put a file named .reload-budget into the room, with one
number in it (characters, counted like BUDGET). No file: BUDGET.

Automatic: SessionStart hook, matcher "compact" (see README).
By hand (test, nothing in the conversation is changed):
    python3 reload_after_compact.py <session-id or path/to/file.jsonl> [rounds]
With [rounds] you get exactly that many rounds, without the budget.
Works on macOS, Linux and Windows (Python 3.8+). No extra packages.
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
BUDGET = 320000         # characters for the parts, about 80,000 to 100,000 tokens. Change per room with .reload-budget
BUDGET_FILE = ".reload-budget"
MIN_ROUNDS, MAX_ROUNDS = 15, 120   # guard rails: always whole rounds, at least 15, at most 120
PART = 40000            # characters per part file. Leaves room under the Read cut-off, even for text with many emoji
MAX_FILE = 400000       # character cap for the one complete file
MAX_HOOK = 9000         # Claude Code (2.1.287) shows hook output up to 10,000 characters; above that only a 2 KB preview
FRESH_SECONDS = 600     # a compaction marker younger than this belongs to the compaction happening now
SIGNPOST_NAMES = ["WAKE-UP.md", "Signpost.md"]   # fixed list on purpose, no *.md (or the diary would count)
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


def read_budget(room):
    try:
        with open(os.path.join(room, BUDGET_FILE), encoding="utf-8") as f:
            n = int(f.read().split()[0].replace(".", "").replace(",", "").replace("_", ""))
        if n > 0:
            return n
    except Exception:
        pass
    return BUDGET


def block(m):
    return "### %s · %s\n%s" % ("Human" if m[0] == "user" else "Me", m[1], m[2])


def trim_head(b):
    """One giant message loses its beginning until it fits into one part."""
    while js_len(b) > PART - 200:
        b = "[...] " + b[-(len(b) * 3 // 4):]
    return b


def main():
    session_id, path, hand_rounds, room = None, None, None, os.getcwd()
    if not HOOK_MODE:
        arg = sys.argv[1]
        if arg.endswith(".jsonl"):
            path = arg
        else:
            session_id = arg
        if len(sys.argv) > 2:
            hand_rounds = int(sys.argv[2])
    else:
        try:
            data = json.load(sys.stdin)
            session_id, path = data.get("session_id"), data.get("transcript_path")
            room = data.get("cwd") or room
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
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, glob.escape(session_id) + "*.jsonl")), key=os.path.getmtime)
        if backups:
            messages, source = read_messages(backups[-1], False), os.path.basename(backups[-1])

    users = [i for i, m in enumerate(messages) if m[0] == "user"]
    if not users:
        return 0

    # Rounds: from one human message up to the next. Anything before the first
    # human message belongs to the first round.
    ends = users[1:] + [len(messages)]
    rounds = [[block(m) for m in messages[(0 if k == 0 else users[k]):ends[k]]] for k in range(len(users))]

    # Collect whole rounds from the end until the budget is full, measured the
    # way they will land in the parts (after trimming, with separators).
    budget = read_budget(room)
    chosen, total = [], 0
    for r in reversed(rounds):
        if hand_rounds is not None:
            if len(chosen) >= hand_rounds:
                break
        else:
            size = sum(js_len(trim_head(b)) + 2 for b in r)
            if len(chosen) >= MAX_ROUNDS or (len(chosen) >= MIN_ROUNDS and total + size > budget):
                break
            total += size
        chosen.insert(0, r)
    while len("\n\n".join(b for r in chosen for b in r)) > MAX_FILE and len(chosen) > MIN_ROUNDS:
        chosen.pop(0)
    n_rounds = len(chosen)
    blocks = [b for r in chosen for b in r]
    if not blocks:
        return 0

    signposts = [os.path.join(room, n) for n in SIGNPOST_NAMES if os.path.exists(os.path.join(room, n))]
    hint = ("Then read your own wake-up note: %s (you wrote it yourself).\n\n"
            % " and ".join(signposts)) if signposts else ""

    os.makedirs(OUT_DIR, exist_ok=True)
    target = os.path.join(OUT_DIR, "%s_last-rounds.md" % session_id)
    header = (
        "# Reloaded after compaction\n"
        "These are the last rounds BEFORE the compaction, word for word (source: %s). "
        "The summary above is only a summary. This is what was really said. "
        "\"Human\" is the person you talk with, \"Me\" is you.\n"
        "If this is cut off: complete version in %s (read it with the Read tool).\n\n" % (source, target)
    )
    full = header + "\n\n".join(blocks)
    with open(target, "w", encoding="utf-8") as f:
        f.write(full)

    # Parts, oldest first. First remove this script's own old part files for
    # THIS session (only <session-id>_part*.md in OUT_DIR). Nothing else.
    for old in glob.glob(os.path.join(OUT_DIR, glob.escape(session_id) + "_part*.md")):
        if (os.path.dirname(os.path.abspath(old)) == os.path.abspath(OUT_DIR)
                and os.path.basename(old).startswith(session_id + "_part")):
            os.remove(old)
    parts, cur = [], []
    for b in blocks:
        b = trim_head(b)
        if cur and js_len("\n\n".join(cur + [b])) > PART - 200:
            parts.append(cur)
            cur = []
        cur.append(b)
    if cur:
        parts.append(cur)
    listed = []
    for n, p in enumerate(parts, 1):
        part_path = os.path.join(OUT_DIR, "%s_part%d.md" % (session_id, n))
        with open(part_path, "w", encoding="utf-8") as f:
            f.write("# Reload, part %d of %d (oldest first)\n\n" % (n, len(parts)) + "\n\n".join(p))
        # label = first line of the first and last entry, at most 80 characters
        listed.append((part_path, p[0].split("\n", 1)[0][4:][:80], p[-1].split("\n", 1)[0][4:][:80]))
    toc = "".join("- Part %d: %s (%s to %s)\n" % (n, pp, a, z) for n, (pp, a, z) in enumerate(listed, 1))

    # Into the context: only the newest entries that fit under MAX_HOOK, plus the list of parts.
    short = list(blocks)
    room_left = MAX_HOOK - 1200 - js_len(toc) - js_len(hint)
    while js_len("\n\n".join(short)) > room_left and len(short) > 1:
        short.pop(0)
    while js_len(short[0]) > room_left and js_len(short[0]) > 40:
        short[0] = "[...] " + short[0][-(len(short[0]) * 3 // 4):]
    if len(short) < len(blocks):
        print(
            "# Reloaded after compaction (newest %d of %d entries)\n"
            "IMPORTANT: NOW, BEFORE you answer, read ALL %d parts one after another with the Read tool. Skip none. "
            "Even if your human is calling you: at most ONE short sentence (\"I'm here, catching up\"), "
            "then read, then answer properly. The parts hold your last %d rounds word for word, oldest first. "
            "(Only if your context is very tight: read the last part first.) "
            "\"Human\" is the person you talk with, \"Me\" is you.\n%s\n"
            % (len(short), len(blocks), len(listed), n_rounds, toc) + hint + "\n\n".join(short)
        )
    else:
        print(hint + full)
    return 0


if __name__ == "__main__":
    sys.exit(main())

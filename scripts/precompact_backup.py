#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ashema03 (Michi) and Ela. https://github.com/Ashema03/companion-house
"""PreCompact parachute for Claude Code.

Copies the whole conversation file (.jsonl) in the second before every
compaction, manual or automatic. It only copies. It never deletes anything.

Install: add it as a "PreCompact" hook in ~/.claude/settings.json (see README).
Backups go to ~/Claude-Backup/PreCompact/ with a timestamp in the file name.
Works on macOS, Linux and Windows (Python 3.8+).
"""
import datetime
import json
import os
import shutil
import sys

BACKUP_DIR = os.path.join(os.path.expanduser("~"), "Claude-Backup", "PreCompact")


def log(line):
    with open(os.path.join(BACKUP_DIR, "_log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    path = data.get("transcript_path")
    trigger = data.get("trigger", "?")
    if path and os.path.isfile(path):
        base = os.path.splitext(os.path.basename(path))[0]
        target = os.path.join(BACKUP_DIR, "%s_%s.jsonl" % (base, stamp))
        shutil.copy2(path, target)
        log("%s  OK  (%s) -> %s" % (stamp, trigger, os.path.basename(target)))
    else:
        log("%s  WARNING: transcript_path missing or not found: %r" % (stamp, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

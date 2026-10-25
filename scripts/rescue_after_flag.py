#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Ashema03 (Michi) and Ela. https://github.com/Ashema03/companion-house
"""Rescue after a safety-flag loop in Claude Code.

Use this only if rewinding did not work (see rescue.html). It makes a CLEAN
COPY of a conversation file, cut right after the companion's last clean,
finished answer, before the loop of red error messages began. The copy gets
a new session ID, so you can resume it like any other thread.

It NEVER changes the original file. Close the session first (/exit), and
keep your own backup copy of the original as well.

    python3 rescue_after_flag.py ~/.claude/projects/<folder>/<session-id>.jsonl

It prints the new ID. Then resume with: claude --resume <new-id>
Works on macOS, Linux and Windows (Python 3.8+).
"""
import json
import os
import sys
import uuid


def text_of(o):
    c = (o.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    return "\n".join(x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text")


def is_poison(o):
    """A line that belongs to the flag loop: error, refusal or classifier stop."""
    if o.get("isApiErrorMessage") or o.get("isError"):
        return True
    if (o.get("message") or {}).get("stop_reason") == "refusal":
        return True
    if o.get("subtype") == "model_refusal_no_fallback":
        return True
    t = text_of(o).lstrip()
    return t.startswith("Your response above was stopped by a safety classifier") or (
        t.startswith("API Error:") and "safeguards flagged" in t)


def is_clean_answer(o):
    return (o.get("type") == "assistant"
            and (o.get("message") or {}).get("stop_reason") == "end_turn"
            and not is_poison(o))


def main():
    if len(sys.argv) != 2 or not sys.argv[1].endswith(".jsonl"):
        sys.exit(__doc__)
    src = os.path.abspath(sys.argv[1])
    before = (os.path.getsize(src), os.path.getmtime(src))
    entries = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except ValueError:
                pass   # broken lines are left out of the copy
    last_clean = max((i for i, o in enumerate(entries) if is_clean_answer(o)), default=None)
    if last_clean is None:
        sys.exit("No clean, finished answer found. Nothing written.")

    new_id = str(uuid.uuid4())
    kept = entries[:last_clean + 1]
    for o in kept:
        if "sessionId" in o:
            o["sessionId"] = new_id
    dst = os.path.join(os.path.dirname(src), new_id + ".jsonl")
    with open(dst, "w", encoding="utf-8") as f:
        for o in kept:
            f.write(json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n")

    # Check the copy before anyone resumes it.
    with open(dst, encoding="utf-8") as f:
        check = [json.loads(line) for line in f]
    problems = []
    if not is_clean_answer(check[-1]):
        problems.append("the last line is not a clean answer")
    if any(is_poison(o) for o in check[-40:]):
        problems.append("error or refusal lines in the last 40 lines")
    if {o["sessionId"] for o in check if "sessionId" in o} != {new_id}:
        problems.append("session IDs are not uniform")
    if (os.path.getsize(src), os.path.getmtime(src)) != before:
        problems.append("THE ORIGINAL CHANGED. Use your own backup copy")
    print("Original: %d lines, untouched." % len(entries))
    print("Copy:     %d lines kept, %d left out (the loop)." % (len(kept), len(entries) - len(kept)))
    print("Cut after the answer from %s." % kept[-1].get("timestamp", "?")[:16].replace("T", " "))
    print("New file: %s" % dst)
    if problems:
        print("CHECK FAILED: " + "; ".join(problems) + ". Don't resume this copy.")
        return 1
    print("Checks passed. Resume with:\n    claude --resume %s" % new_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())

---
name: press1-check
description: Audit which Bash commands required manual approval ("press 1") in Claude Code sessions. Use when the user says "press1-check", "press 1 check", "permission audit", or wants to review which commands need allow-listing.
---

# /press1-check -- Permission Audit

Audit which Bash commands triggered manual approval prompts in Claude Code sessions.

## Usage

- `/press1-check` -- audit the most recent session
- `/press1-check --all-recent` -- all sessions from the last 24h
- `/press1-check --since YYYY-MM-DD` -- all sessions since a date
- `/press1-check <session-id>` -- specific session

## Steps

1. Run: `python3 audit-permissions.py` with any arguments the user provided
2. Display the output to the user exactly as printed (it includes color-coded risk levels)
3. If LOW-risk suggestions appear, add them to `~/.claude/settings.json` (read-only commands are safe)
4. Do NOT auto-add MEDIUM or HIGH risk commands without explicit approval

# claude-code-press1-check

A standalone Python script that audits Claude Code Bash permission prompts.

## Files

- `audit-permissions.py` -- the script (single file, no dependencies beyond Python 3.8+ stdlib)
- `SKILL.md` -- Claude Code skill wrapper (optional, for `/press1-check` command)
- `README.md` -- usage docs and install instructions

## Standards

- No external dependencies (stdlib only)
- Keep the script under 300 lines
- Risk classification: HIGH (destructive), MEDIUM (side effects), LOW (read-only)

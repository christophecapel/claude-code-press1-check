#!/usr/bin/env python3
"""Audit which Bash commands required manual approval in Claude Code sessions.

Usage:
  audit-permissions.py                    # most recent session
  audit-permissions.py --all-recent       # all sessions from last 24h
  audit-permissions.py --since 2026-04-10 # all sessions since date
  audit-permissions.py <session-id>       # specific session
  audit-permissions.py --help             # show this help

Reads the session JSONL transcript and checks each Bash tool_use against
the allow list in ~/.claude/settings.json. Outputs commands with risk
levels and suggests allow rules to add.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# --- Risk classification ---

# HIGH: destructive or hard to reverse. Keep gated.
HIGH_RISK_PATTERNS = [
    "rm ", "rm\t", "rmdir",
    "git reset", "git clean", "git push --force", "git push -f",
    "git branch -D", "git branch -d",
    "git checkout -- ", "git restore",
    "chmod", "chown",
    "kill", "pkill",
    "sudo",
    "curl.*POST", "curl.*PUT", "curl.*DELETE",
    "gh issue close", "gh pr close", "gh pr merge",
    "DROP ", "DELETE FROM", "TRUNCATE",
]

# MEDIUM: side effects outside local repo. Review before allowing.
MEDIUM_RISK_PATTERNS = [
    "gh release", "gh pr create", "gh issue create",
    "git push",
    "curl", "wget",
    "open ",  # opens apps/URLs
    "ssh", "scp", "rsync",
    "pip install", "npm install", "brew install",
    "docker", "kubectl",
]

# LOW: read-only or local-only. Safe to auto-approve.
# Everything not matching HIGH or MEDIUM is LOW by default.


def classify_risk(command: str) -> str:
    """Classify a command's risk level."""
    cmd_lower = command.lower()
    for pattern in HIGH_RISK_PATTERNS:
        if pattern.lower() in cmd_lower:
            return "HIGH"
    for pattern in MEDIUM_RISK_PATTERNS:
        if pattern.lower() in cmd_lower:
            return "MEDIUM"
    return "LOW"


RISK_LABELS = {
    "HIGH": "\033[91mHIGH\033[0m",    # red
    "MEDIUM": "\033[93mMEDIUM\033[0m",  # yellow
    "LOW": "\033[92mLOW\033[0m",        # green
}

RISK_ADVICE = {
    "HIGH": "KEEP GATED -- destructive or hard to reverse",
    "MEDIUM": "REVIEW -- has side effects outside local repo",
    "LOW": "SAFE TO ADD -- read-only or local-only",
}

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def find_sessions_dir() -> Path:
    """Auto-detect the Claude Code sessions directory.

    Strategy:
    1. Encode CWD the way Claude Code does (/ -> -) and check for that project dir.
    2. Fall back to the project dir with the most recently modified .jsonl file.
    """
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        print(f"Claude Code projects directory not found: {projects_dir}")
        sys.exit(1)

    # Try CWD-based encoding first
    cwd = str(Path.cwd())
    encoded = cwd.replace("/", "-")
    candidate = projects_dir / encoded
    if candidate.exists() and any(candidate.glob("*.jsonl")):
        return candidate

    # Fallback: find project dir with most recent session
    best = None
    best_mtime = 0
    for d in projects_dir.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("*.jsonl"):
            mt = f.stat().st_mtime
            if mt > best_mtime:
                best_mtime = mt
                best = d
            break
    if best:
        return best

    print("No Claude Code sessions found.")
    sys.exit(1)


def load_allow_prefixes() -> list[str]:
    """Extract Bash allow prefixes from settings.json."""
    try:
        settings = json.loads(SETTINGS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    prefixes = []
    for rule in settings.get("permissions", {}).get("allow", []):
        if rule.startswith("Bash(") and rule.endswith(")"):
            pattern = rule[5:-1]  # strip Bash( and )
            if pattern.endswith(":*"):
                pattern = pattern[:-2]  # strip :*
            elif pattern.endswith("*"):
                pattern = pattern[:-1]  # strip *
            prefixes.append(pattern)
    return prefixes


def find_sessions(sessions_dir: Path, session_id: str = None,
                  all_recent: bool = False, since: str = None) -> list[Path]:
    """Find session JSONL files to audit.

    Returns both main session files and subagent session files.
    """
    if session_id:
        path = sessions_dir / f"{session_id}.jsonl"
        if path.exists():
            results = [path]
        else:
            results = list(sessions_dir.glob(f"{session_id}*.jsonl"))
            if not results:
                print(f"Session not found: {session_id}")
                sys.exit(1)
        # Also include subagent files for matched sessions
        for r in list(results):
            sub_dir = sessions_dir / r.stem / "subagents"
            if sub_dir.exists():
                results.extend(sub_dir.glob("*.jsonl"))
        return results

    # Collect all JSONL files (main + subagent)
    jsonl_files = list(sessions_dir.glob("*.jsonl"))
    for d in sessions_dir.iterdir():
        if d.is_dir():
            sub_dir = d / "subagents"
            if sub_dir.exists():
                jsonl_files.extend(sub_dir.glob("*.jsonl"))

    jsonl_files = sorted(jsonl_files, key=lambda p: p.stat().st_mtime, reverse=True)

    if since:
        cutoff = datetime.strptime(since, "%Y-%m-%d").timestamp()
        return [f for f in jsonl_files if f.stat().st_mtime > cutoff]

    if all_recent:
        import time
        cutoff = time.time() - 86400
        return [f for f in jsonl_files if f.stat().st_mtime > cutoff]

    # Default: most recent session (main file only) + its subagents
    main_files = [f for f in jsonl_files if "/subagents/" not in str(f)]
    if main_files:
        latest = main_files[0]
        results = [latest]
        sub_dir = sessions_dir / latest.stem / "subagents"
        if sub_dir.exists():
            results.extend(sub_dir.glob("*.jsonl"))
        return results

    print("No sessions found.")
    sys.exit(1)


def is_subagent(path: Path) -> bool:
    """Check if a session file is from a subagent."""
    return "/subagents/" in str(path) or "\\subagents\\" in str(path)


def session_display_name(path: Path) -> str:
    """Get a display name for a session file."""
    if is_subagent(path):
        parent_id = path.parent.parent.name[:12]
        return f"{parent_id} [subagent: {path.stem[:16]}]"
    return path.stem


def audit_session(path: Path, prefixes: list[str]) -> list[dict]:
    """Find Bash commands that aren't covered by the allow list."""
    needs_approval = []
    subagent = is_subagent(path)

    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
            except (json.JSONDecodeError, ValueError):
                continue

            if d.get("type") != "assistant":
                continue

            msg = d.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    cmd = block.get("input", {}).get("command", "")
                    if not cmd:
                        continue
                    cmd_stripped = cmd.strip()
                    matched = any(cmd_stripped.startswith(p) for p in prefixes)
                    if not matched:
                        risk = classify_risk(cmd_stripped)
                        needs_approval.append({
                            "command": cmd_stripped[:200],
                            "session": session_display_name(path),
                            "risk": risk,
                            "subagent": subagent,
                        })

    return needs_approval


def suggest_rules(commands: list[dict]) -> list[str]:
    """Suggest allow rules for unmatched commands."""
    suggestions = {}
    for item in commands:
        cmd = item["command"]
        first_word = cmd.split()[0] if cmd.split() else cmd
        # Handle env var prefixes like GIT_DIR=...
        if "=" in first_word and not first_word.startswith("-"):
            rule = f'Bash({first_word.split("=")[0]}=*)'
        else:
            rule = f'Bash({first_word}:*)'
        # Keep the highest risk level for each suggestion
        if rule not in suggestions or RISK_ORDER[item["risk"]] > RISK_ORDER[suggestions[rule]]:
            suggestions[rule] = item["risk"]
    return sorted(suggestions.items(), key=lambda x: RISK_ORDER[x[1]])


def main():
    parser = argparse.ArgumentParser(
        description="Audit which Bash commands required manual approval in Claude Code sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s                         most recent session
  %(prog)s --all-recent            all sessions from last 24h
  %(prog)s --since 2026-04-10      all sessions since April 10
  %(prog)s abc123                   specific session (prefix match OK)""",
    )
    parser.add_argument("session_id", nargs="?", help="specific session ID (prefix match OK)")
    parser.add_argument("--all-recent", action="store_true", help="audit all sessions from the last 24h")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="audit all sessions since this date")
    args = parser.parse_args()

    sessions_dir = find_sessions_dir()
    prefixes = load_allow_prefixes()
    if not prefixes:
        print("Warning: no allow prefixes found in settings.json")

    sessions = find_sessions(sessions_dir, args.session_id, args.all_recent, args.since)
    all_needs = []

    # Group by main session for display
    current_session = None
    for path in sessions:
        needs = audit_session(path, prefixes)
        if needs:
            display = session_display_name(path)
            # Show session header for main sessions
            main_id = path.stem if not is_subagent(path) else path.parent.parent.name
            if main_id != current_session:
                current_session = main_id
                print(f"\n{'='*60}")
                print(f"Session: {main_id}")
                print(f"{'='*60}")
            for item in needs:
                label = RISK_LABELS[item["risk"]]
                tag = " [subagent]" if item["subagent"] else ""
                print(f"  [{label}]{tag} {item['command'][:120]}")
            all_needs.extend(needs)

    if not all_needs:
        print("All Bash commands were covered by the allow list.")
        return

    # Summary by risk
    by_risk = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    subagent_count = sum(1 for item in all_needs if item["subagent"])
    for item in all_needs:
        by_risk[item["risk"]] += 1

    print(f"\n{'='*60}")
    summary = f"SUMMARY: {by_risk['LOW']} low, {by_risk['MEDIUM']} medium, {by_risk['HIGH']} high"
    if subagent_count:
        summary += f" ({subagent_count} from subagents)"
    print(summary)
    print(f"{'='*60}")

    suggestions = suggest_rules(all_needs)
    print(f"\nSUGGESTED ADDITIONS to ~/.claude/settings.json:")
    print(f"(sorted by risk -- add LOW freely, review MEDIUM, skip HIGH)\n")
    for rule, risk in suggestions:
        label = RISK_LABELS[risk]
        advice = RISK_ADVICE[risk]
        print(f'  [{label}] "{rule}",  -- {advice}')


if __name__ == "__main__":
    main()

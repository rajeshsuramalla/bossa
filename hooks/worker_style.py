#!/usr/bin/env python3
"""SubagentStart hook for the bossa plugin: tell worker subagents to report tersely.

Injects the report-style rules as additionalContext into bossa's workers (agent_type starting
with "bossa:" or one of the bare worker names). The architect never gets them. Set
BOSSA_WORKER_STYLE=0 to turn the hook off. Unreadable input fails open: nothing is injected.
"""
import json
import os
import sys
from typing import List, Optional

EXIT_OK = 0
EXIT_SELFTEST_FAILED = 1

PLUGIN = "bossa"
PREFIX = PLUGIN + ":"
ARCHITECT = ("architect", PREFIX + "architect")
BARE_WORKERS = (
    "scout",
    "implementer",
    "hard-implementer",
    "code-reviewer",
    "security-reviewer",
    "git-ops",
)
DISABLE_VARIABLE = "BOSSA_WORKER_STYLE"
DISABLED_VALUE = "0"

RULES = (
    "WORKER REPORT STYLE ACTIVE. Your final report and every message to the coordinator "
    "lead with the status (done, partial or blocked), then list the files changed with one "
    "phrase each, the behaviour changed and preserved, the tests run with their exact "
    "results, remaining risks, and questions for the coordinator. Be terse: drop articles, "
    "filler, pleasantries and hedging; fragments are fine; one idea per sentence; no "
    "tool-call narration. Keep code, paths, identifiers, commands, numbers, test summary "
    "lines and error strings exact. Never drop not, no, only or except. Do not paste code "
    "or file dumps into the report unless asked. Prose you write into files (code comments, "
    "docstrings, commit messages, docs) stays normal English."
)


def is_worker(agent_type: str) -> bool:
    """True for bossa's workers: plugin-scoped or bare names, never the architect."""
    if agent_type in ARCHITECT:
        return False
    return agent_type.startswith(PREFIX) or agent_type in BARE_WORKERS


def evaluate(raw: str, environ: Optional[dict] = None) -> Optional[str]:
    """Return the JSON to print for one SubagentStart payload, or None to inject nothing."""
    env = os.environ if environ is None else environ
    if env.get(DISABLE_VARIABLE) == DISABLED_VALUE:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    agent_type = payload.get("agent_type")
    if not isinstance(agent_type, str) or not is_worker(agent_type.strip()):
        return None
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": RULES}}
    )


def _selftest_cases() -> List[tuple]:
    start = '{"hook_event_name": "SubagentStart", "agent_type": "%s"}'
    return [
        ("bare worker", start % "scout", {}, True),
        ("bare git-ops", start % "git-ops", {}, True),
        ("plugin-scoped worker", start % "bossa:code-reviewer", {}, True),
        ("bare architect", start % "architect", {}, False),
        ("scoped architect", start % "bossa:architect", {}, False),
        ("foreign agent", start % "general-purpose", {}, False),
        ("disabled by env", start % "scout", {DISABLE_VARIABLE: DISABLED_VALUE}, False),
        ("env other than 0 keeps it on", start % "scout", {DISABLE_VARIABLE: "1"}, True),
        ("missing agent_type", '{"hook_event_name": "SubagentStart"}', {}, False),
        ("bad JSON", "not json", {}, False),
        ("JSON list", "[1, 2]", {}, False),
    ]


def selftest() -> int:
    """Run the built-in cases and report how many pass."""
    cases = _selftest_cases()
    failures = []
    for name, raw, environ, injects in cases:
        out = evaluate(raw, environ)
        ok = out is not None
        if ok:
            ctx = json.loads(out)["hookSpecificOutput"]
            ok = ctx == {"hookEventName": "SubagentStart", "additionalContext": RULES}
        if ok != injects:
            failures.append("FAIL %s: want inject=%s, got %s" % (name, injects, ok))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return EXIT_SELFTEST_FAILED
    print("bossa worker_style selftest: %d cases passed" % len(cases))
    return EXIT_OK


def main(argv: List[str]) -> int:
    """Read one SubagentStart event from stdin and print the injection, if any."""
    if "--selftest" in argv[1:]:
        return selftest()
    out = evaluate(sys.stdin.buffer.read().decode("utf-8", "replace"))
    if out:
        print(out)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))

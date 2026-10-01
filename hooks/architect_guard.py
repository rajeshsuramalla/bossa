#!/usr/bin/env python3
"""PreToolUse guard for the bossa plugin.

1. Destructive git is blocked for every caller.
2. Mutating git is blocked for bossa's own agents except git-ops.
3. The architect, as the main session, gets read-only Bash and may not upgrade a
   worker to opus on an Agent call; workers run on their frontmatter model.

Exit 0 allows, exit 2 blocks with the reason on stderr. Unreadable input fails open.
"""
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

EXIT_ALLOW = 0
EXIT_BLOCK = 2
EXIT_SELFTEST_FAILED = 1

PLUGIN = "bossa"
GIT_OPS = ("git-ops", PLUGIN + ":git-ops")
ARCHITECT = ("architect", PLUGIN + ":architect")
BARE_AGENTS = (
    "architect",
    "scout",
    "implementer",
    "hard-implementer",
    "code-reviewer",
    "security-reviewer",
    "git-ops",
)
FORBIDDEN_WORKER_MODEL = "opus"

# Known ceiling: wrappers with options (env -i, sudo -u), bash -c and eval are not unwrapped.
LINE_CONTINUATION = re.compile(r"\\\r?\n")
BLANKS = re.compile(r"[ \t]+")
QUOTED_OR_WORD = r"""(?:"[^"]*"|'[^']*'|\S+)"""
ASSIGNMENT = r"""[A-Za-z_]\w*=(?:"[^"]*"|'[^']*'|\S*)"""
WRAPPERS = re.compile(
    r"(^|[;&|(`]) *(?:(?:" + ASSIGNMENT + r"|env|command|sudo) +)+", re.MULTILINE
)

# Git global options that may sit between `git` and the subcommand.
GIT_OPTION = (
    r"(?:-[Cc] +" + QUOTED_OR_WORD
    + r"|--(?:git-dir|work-tree|namespace) +" + QUOTED_OR_WORD
    + r"|--[a-z][a-z-]*(?:=(?:\"[^\"]*\"|'[^']*'|\S*))?)"
)
GIT = r"git(?: +" + GIT_OPTION + r")* +"
COMMAND_START = r"(?:^|[;&|(`] *)"
SUBCOMMAND_END = r"(?=[\s;&|)`]|$)"
DESTRUCTIVE = re.compile(
    COMMAND_START
    + GIT
    + r"(?:push(?: .*)? (?:--force[a-z-]*(?:=\S*)?|--mirror|-[a-z]*f[a-z]*|\+\S+)"
    + r"|reset(?: .*)? --hard"
    + r"|clean"
    + r"|(?:commit|push)(?: .*)? --no-verify)"
    + SUBCOMMAND_END,
    re.MULTILINE,
)
GIT_WRITE = re.compile(
    COMMAND_START
    + GIT
    + r"(?:add|commit|push|pull|fetch|merge|rebase|cherry-pick|revert|reset|checkout"
    + r"|switch|restore|stash|tag|rm|mv|apply|am|worktree"
    + r"|branch +(?:-[dDmM]|--delete|--move))"
    + SUBCOMMAND_END,
    re.MULTILINE,
)
CHAINING = re.compile(r"[;&|`<>\r\n]|\$\(|--output")
ARCHITECT_BASH = re.compile(r"(?:git (?:status|diff|log|show|blame)|ls|pwd)(?: |$)")

BLOCK_DESTRUCTIVE = "force push, reset --hard, clean and --no-verify are never allowed."
BLOCK_GIT_WRITE = "only git-ops may change git state. Report back so the architect can delegate it."
BLOCK_MODEL = (
    "the architect may not upgrade a worker to opus; workers run on their "
    "frontmatter model. Omit the model parameter."
)
BLOCK_CHAINING = "one read-only command, no chaining or redirection."
BLOCK_ARCHITECT_BASH = (
    "architect Bash is limited to git status, diff, log, show, blame, ls, pwd. "
    "Use scout, a reviewer or git-ops."
)


def _text(source: Dict, key: str) -> str:
    """Return source[key] as a string, or an empty string when absent."""
    value = source.get(key)
    return "" if value is None else str(value)


def _is_bossa_agent(agent_type: str) -> bool:
    """Tell this plugin's agents from other plugins' and the user's own."""
    return agent_type.startswith(PLUGIN + ":") or agent_type in BARE_AGENTS


def _collapse(command: str) -> str:
    """Join continued lines and squeeze runs of blanks so patterns see one spacing."""
    return BLANKS.sub(" ", LINE_CONTINUATION.sub("", command)).strip()


def _unwrap(command: str) -> str:
    """Drop VAR=val, env, command and sudo prefixes that hide a git command."""
    return WRAPPERS.sub(r"\1", command)


def check(event: Dict) -> Optional[str]:
    """Return the reason to block this tool call, or None to allow it."""
    tool = _text(event, "tool_name")
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input is not an object")
    agent_id = _text(event, "agent_id")
    agent_type = _text(event, "agent_type")
    command = _collapse(_text(tool_input, "command"))

    if tool == "Bash":
        git_view = _unwrap(command)
        if DESTRUCTIVE.search(git_view):
            return BLOCK_DESTRUCTIVE
        if _is_bossa_agent(agent_type) and agent_type not in GIT_OPS:
            if GIT_WRITE.search(git_view):
                return BLOCK_GIT_WRITE

    if agent_id or agent_type not in ARCHITECT:
        return None

    if tool == "Agent":
        if FORBIDDEN_WORKER_MODEL in _text(tool_input, "model").lower():
            return BLOCK_MODEL
    elif tool == "Bash":
        if CHAINING.search(command):
            return BLOCK_CHAINING
        if not ARCHITECT_BASH.match(command):
            return BLOCK_ARCHITECT_BASH
    return None


def evaluate(raw: str) -> Tuple[int, str]:
    """Turn raw hook input into an exit code and a stderr message."""
    try:
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("hook input is not a JSON object")
        reason = check(event)
    except ValueError as error:
        return EXIT_ALLOW, "bossa guard: unreadable hook input (%s); allowing" % error
    if reason:
        return EXIT_BLOCK, "Blocked: " + reason
    return EXIT_ALLOW, ""


def _call(tool: str, agent_type: str = "", agent_id: str = "", **tool_input: str) -> str:
    return json.dumps(
        {
            "tool_name": tool,
            "agent_type": agent_type,
            "agent_id": agent_id,
            "tool_input": tool_input,
        }
    )


def _selftest_cases() -> List[Tuple[str, str, int]]:
    def bash(command: str, agent_type: str = "", agent_id: str = "") -> str:
        return _call("Bash", agent_type, agent_id, command=command)

    def spawn(agent_type: str, **tool_input: str) -> str:
        return _call("Agent", agent_type, **tool_input)

    architect = PLUGIN + ":architect"
    scout = "scout"
    ops = "git-ops"
    other = "other-plugin:worker"
    return [
        ("force push, any caller", bash("git push origin x -f", "implementer"), EXIT_BLOCK),
        ("reset --hard, plain session", bash("git reset --hard HEAD~1"), EXIT_BLOCK),
        ("--no-verify, even for git-ops", bash("git commit --no-verify", ops), EXIT_BLOCK),
        ("git clean, namespaced git-ops", bash("git clean -fd", PLUGIN + ":git-ops"), EXIT_BLOCK),
        ("force push behind -C", bash("git -C . push --force", ops), EXIT_BLOCK),
        ("push +ref", bash("git push origin +main", ops), EXIT_BLOCK),
        ("push bundled -uf", bash("git push -uf origin x", ops), EXIT_BLOCK),
        ("push --force-with-lease=", bash("git push --force-with-lease=main:abc", ops), EXIT_BLOCK),
        ("push --mirror", bash("git push --mirror", ops), EXIT_BLOCK),
        ("reset flags before --hard", bash("git reset HEAD~1 --hard", ops), EXIT_BLOCK),
        ("commit message mentions -n", bash('git commit -m "fix -n flag"', ops), EXIT_ALLOW),
        ("clean behind VAR=val", bash("FOO=1 git clean -fd", ops), EXIT_BLOCK),
        ("clean named in a message", bash("git commit -m 'git clean up docs'", ops), EXIT_ALLOW),
        ("grep for git clean", bash('grep -rn "git clean"', scout), EXIT_ALLOW),
        ("commit by namespaced worker", bash("git commit", PLUGIN + ":implementer"), EXIT_BLOCK),
        ("commit by bare worker", bash("git commit -m x", "implementer"), EXIT_BLOCK),
        ("commit chained after cd", bash("cd x && git commit -m y", scout), EXIT_BLOCK),
        ("commit by namespaced scout", bash("git commit", PLUGIN + ":scout"), EXIT_BLOCK),
        ("commit by bare scout", bash("git commit", scout), EXIT_BLOCK),
        ("commit after line continuation", bash("git \\\ncommit", scout), EXIT_BLOCK),
        ("commit with a tab", bash("git\tcommit", scout), EXIT_BLOCK),
        ("commit behind VAR=val", bash("GIT_EDITOR=true git commit", scout), EXIT_BLOCK),
        ("commit behind env", bash("env git commit", scout), EXIT_BLOCK),
        ("commit behind sudo", bash("sudo git commit", scout), EXIT_BLOCK),
        ("commit behind command", bash("command git commit", scout), EXIT_BLOCK),
        ("commit behind VAR=val after &&", bash("cd x && FOO=1 git commit", scout), EXIT_BLOCK),
        ("commit after --opt=val", bash("git --git-dir=.git commit", scout), EXIT_BLOCK),
        ("commit after --opt flag", bash("git --no-pager commit", scout), EXIT_BLOCK),
        ("commit after --opt value", bash("git --git-dir .git commit", scout), EXIT_BLOCK),
        ("commit after quoted -C", bash('git -C "my repo" commit', scout), EXIT_BLOCK),
        ("commit after quoted -c", bash("git -c 'a.b=c d' commit", scout), EXIT_BLOCK),
        ("commit ended by semicolon", bash("git commit;ls", scout), EXIT_BLOCK),
        ("commit in a subshell", bash("(git commit)", scout), EXIT_BLOCK),
        ("stash list is still stash", bash("git stash list", scout), EXIT_BLOCK),
        ("worker reads git log", bash("git log --oneline", scout), EXIT_ALLOW),
        ("worker reads status behind -C", bash("git -C x status", scout), EXIT_ALLOW),
        ("worker lists branches", bash("git branch", scout), EXIT_ALLOW),
        ("commit by other plugin agent", bash("git commit", other), EXIT_ALLOW),
        ("force push, other plugin agent", bash("git push -f", other), EXIT_BLOCK),
        ("commit by bare git-ops", bash("git commit -m x", ops), EXIT_ALLOW),
        ("commit by namespaced git-ops", bash("git commit -m x", PLUGIN + ":git-ops"), EXIT_ALLOW),
        ("commit by plain session", bash("git commit -m x"), EXIT_ALLOW),
        ("worker runs tests", bash("npm test", PLUGIN + ":implementer"), EXIT_ALLOW),
        ("architect git status", bash("git status --short", architect), EXIT_ALLOW),
        ("bare architect ls", bash("ls -la", "architect"), EXIT_ALLOW),
        ("architect pipe", bash("git diff | head", architect), EXIT_BLOCK),
        ("architect newline chain", bash("git status\nrm -rf x", architect), EXIT_BLOCK),
        ("architect continued pipe", bash("git status \\\n| head", architect), EXIT_BLOCK),
        ("architect redirect", bash("git log > out.txt", architect), EXIT_BLOCK),
        ("architect substitution", bash("ls $(pwd)", architect), EXIT_BLOCK),
        ("architect env prefix", bash("env git status", architect), EXIT_BLOCK),
        ("architect off-list command", bash("npm test", architect), EXIT_BLOCK),
        ("architect as subagent", bash("npm test", architect, agent_id="a1"), EXIT_ALLOW),
        ("architect passes opus", spawn(architect, model="opus"), EXIT_BLOCK),
        ("architect passes full opus id", spawn(architect, model="claude-opus-5-5"), EXIT_BLOCK),
        ("architect passes sonnet", spawn(architect, model="sonnet"), EXIT_ALLOW),
        ("architect omits model", spawn("architect"), EXIT_ALLOW),
        ("worker passes opus", spawn(PLUGIN + ":implementer", model="opus"), EXIT_ALLOW),
        ("input is not JSON", "not json", EXIT_ALLOW),
        ("input is a JSON list", "[1, 2]", EXIT_ALLOW),
    ]


def selftest() -> int:
    """Run the built-in cases and report how many pass."""
    cases = _selftest_cases()
    failures = []
    for name, raw, expected in cases:
        code, _ = evaluate(raw)
        if code != expected:
            failures.append("FAIL %s: want exit %d, got %d" % (name, expected, code))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return EXIT_SELFTEST_FAILED
    print("bossa guard selftest: %d cases passed" % len(cases))
    return EXIT_ALLOW


def main(argv: List[str]) -> int:
    """Read one PreToolUse event from stdin and exit with the verdict."""
    if "--selftest" in argv[1:]:
        return selftest()
    code, message = evaluate(sys.stdin.buffer.read().decode("utf-8", "replace"))
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))

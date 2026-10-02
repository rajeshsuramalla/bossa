#!/usr/bin/env python3
"""Generate and check bossa's Copilot CLI and Codex CLI files from agents/*.md.

--write regenerates copilot/agents/*.agent.md, codex/agents/*.toml and codex/AGENTS.md.
--selftest parses every manifest and hook file and asserts each generated agent still equals
its Claude source after the substitutions below. Nothing here runs copilot or codex.
"""
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

EXIT_OK = 0
EXIT_FAILED = 1

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_AGENTS = ROOT / "agents"
COPILOT_AGENTS = ROOT / "copilot" / "agents"
CODEX_AGENTS = ROOT / "codex" / "agents"
CODEX_DOC = ROOT / "codex" / "AGENTS.md"
COPILOT_SUFFIX = ".agent.md"

ARCHITECT = "architect"
FRONTMATTER_FENCE = "---"
TOML_MIN_VERSION = (3, 11)
COPILOT_PROMPT_LIMIT = 30000
CODEX_DOC_LIMIT = 32 * 1024
HOOK_TIMEOUT_SECONDS = 10
COPILOT_HOOKS_VERSION = 1
CODEX_LOCAL_SOURCE = {"source": "local", "path": "./"}

# Tool aliases from the Copilot custom-agents reference; the architect gets no edit or execute.
COPILOT_ALIASES = ("execute", "read", "edit", "search", "agent", "web", "todo")
COPILOT_TOOLS = {
    "architect": ["read", "search", "agent"],
    "scout": ["read", "search", "execute"],
    "implementer": ["read", "search", "edit", "execute"],
    "hard-implementer": ["read", "search", "edit", "execute"],
    "code-reviewer": ["read", "search", "execute"],
    "security-reviewer": ["read", "search", "execute"],
    "git-ops": ["read", "search", "execute"],
}
# scout is not read-only: it runs tests and builds, which write.
CODEX_READ_ONLY = ("code-reviewer", "security-reviewer")
CODEX_NOTE = (
    "<!-- bossa architect rules for Codex CLI. "
    "Copy this file to your repo root or to ~/.codex/AGENTS.md. -->\n\n"
)
CODEX_MODEL_LINE = '# model = "<model-name>"\n'

ROUTING_NOTE = (
    "Worker names below are bare. When the Agent tool lists them with a `bossa:`\n"
    "prefix, spawn them by the prefixed name.\n"
)
SPAWN_BY_NAME = (
    "Spawn workers by name: scout, implementer, hard-implementer, code-reviewer,\n"
    "security-reviewer, git-ops.\n"
)
GIT_DIFF_RULE = (
    "Run `git diff` yourself only to settle a disputed finding or to\n"
    "   spot-check a high-risk change.\n"
)
GIT_DIFF_RULE_COPILOT = (
    "Have `scout` run `git diff` only to settle a disputed finding or to\n"
    "   spot-check a high-risk change.\n"
)
FIX_ROUNDTRIP = (
    "8. Valid blockers: message the same worker with numbered corrections, then\n"
    "   message the same reviewer to re-check only those fixes.\n"
)
FIX_ROUNDTRIP_ONE_SHOT = (
    "8. Valid blockers: spawn the same worker type again with the numbered\n"
    "   corrections, then spawn the same reviewer type again to re-check only\n"
    "   those fixes.\n"
)
BASH_SECTION = (
    "## Bash\n"
    "Read-only commands only: git status, git diff, git log, git show, git blame, ls, pwd.\n"
    "Never use Bash to create or modify files. Never run the test suite yourself.\n"
    "Test output belongs in a scout or worker context.\n"
)
SHELL_SECTION_COPILOT = (
    "## Shell\n"
    "This host gives the architect no shell: `git status`, `git diff` and `git log` are\n"
    "unavailable to you, so ask `scout` for them. Never run the test suite yourself.\n"
    "Test output belongs in a scout or worker context.\n"
)


def _swap(text: str, old: str, new: str) -> str:
    """Replace old by new, failing loudly when agents/*.md no longer contains old."""
    if old not in text:
        raise ValueError("agents/*.md changed; update the substitution for: %r" % old[:50])
    return text.replace(old, new)


def parse_frontmatter(text: str, as_json: bool) -> Tuple[Dict[str, object], str]:
    """Split a file into its frontmatter keys and its body; values are JSON when as_json."""
    lines = text.split("\n")
    if lines[0] != FRONTMATTER_FENCE:
        raise ValueError("file does not start with frontmatter")
    end = lines.index(FRONTMATTER_FENCE, 1)
    keys = {}  # type: Dict[str, object]
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        value = value.strip()
        keys[key] = json.loads(value) if as_json else value
    return keys, "\n".join(lines[end + 1 :]).lstrip("\n")


def claude_agents() -> Dict[str, Tuple[Dict[str, object], str]]:
    """Return every Claude agent as name -> (frontmatter, body)."""
    agents = {}
    for path in sorted(CLAUDE_AGENTS.glob("*.md")):
        agents[path.stem] = parse_frontmatter(path.read_text(encoding="utf-8"), as_json=False)
    return agents


def copilot_body(name: str, claude_body: str) -> str:
    """Return the body Copilot's copy of an agent must carry."""
    if name != ARCHITECT:
        return claude_body
    body = codex_body(name, claude_body)
    body = _swap(body, GIT_DIFF_RULE, GIT_DIFF_RULE_COPILOT)
    return _swap(body, BASH_SECTION, SHELL_SECTION_COPILOT)


def codex_body(name: str, claude_body: str) -> str:
    """Return the body Codex's copy of an agent must carry."""
    if name != ARCHITECT:
        return claude_body
    body = _swap(claude_body, ROUTING_NOTE, SPAWN_BY_NAME)
    return _swap(body, FIX_ROUNDTRIP, FIX_ROUNDTRIP_ONE_SHOT)


def copilot_text(name: str, description: str, claude_body: str) -> str:
    """Return the full text of copilot/agents/<name>.agent.md."""
    head = ["name: " + json.dumps(name), "description: " + json.dumps(description)]
    head.append("tools: " + json.dumps(COPILOT_TOOLS[name]))
    if name != ARCHITECT:
        head.append("include-custom-instructions: true")
    return "---\n" + "\n".join(head) + "\n---\n\n" + copilot_body(name, claude_body)


def codex_toml_text(name: str, description: str, claude_body: str) -> str:
    """Return the full text of codex/agents/<name>.toml."""
    body = codex_body(name, claude_body)
    if "'''" in body:
        raise ValueError("%s: body holds ''' and cannot sit in a TOML literal string" % name)
    head = "name = %s\ndescription = %s\n" % (json.dumps(name), json.dumps(description))
    sandbox = 'sandbox_mode = "read-only"\n' if name in CODEX_READ_ONLY else ""
    return head + CODEX_MODEL_LINE + sandbox + "developer_instructions = '''\n" + body + "'''\n"


def codex_doc_text(claude_body: str) -> str:
    """Return the full text of codex/AGENTS.md."""
    return CODEX_NOTE + codex_body(ARCHITECT, claude_body)


def _write(path: Path, text: str) -> None:
    """Write text as UTF-8 with LF endings on every platform."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_all() -> int:
    """Regenerate every host agent file from agents/*.md."""
    COPILOT_AGENTS.mkdir(parents=True, exist_ok=True)
    CODEX_AGENTS.mkdir(parents=True, exist_ok=True)
    for name, (front, body) in claude_agents().items():
        description = str(front["description"])
        _write(COPILOT_AGENTS / (name + COPILOT_SUFFIX), copilot_text(name, description, body))
        if name == ARCHITECT:
            _write(CODEX_DOC, codex_doc_text(body))
        else:
            _write(CODEX_AGENTS / (name + ".toml"), codex_toml_text(name, description, body))
    return EXIT_OK


def _load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_manifests(check: Callable[[str, object, object], None]) -> None:
    """Parse every manifest and hook file and cross-check names, versions and paths."""
    claude = _load_json(ROOT / ".claude-plugin" / "plugin.json")
    copilot = _load_json(ROOT / ".github" / "plugin" / "plugin.json")
    codex = _load_json(ROOT / ".codex-plugin" / "plugin.json")
    for label, manifest in (("claude", claude), ("copilot", copilot), ("codex", codex)):
        check(label + " manifest name", manifest["name"], "bossa")
        check(label + " manifest version", manifest["version"], claude["version"])
    for path in (".claude-plugin/marketplace.json", ".github/plugin/marketplace.json"):
        plugins = _load_json(ROOT / path)["plugins"]
        check(path + " lists bossa", "bossa" in [p["name"] for p in plugins], True)
    codex_market = _load_json(ROOT / ".agents" / "plugins" / "marketplace.json")["plugins"]
    check("codex marketplace source", codex_market[0]["source"], CODEX_LOCAL_SOURCE)
    claude_hooks = _load_json(ROOT / "hooks" / "hooks.json")["hooks"]
    check("claude hooks events", sorted(claude_hooks), ["PreToolUse", "SubagentStart"])

    check("copilot agents dir exists", (ROOT / copilot["agents"]).is_dir(), True)
    check("copilot hooks file exists", (ROOT / copilot["hooks"]).is_file(), True)
    hook = _load_json(ROOT / copilot["hooks"])
    entry = hook["hooks"]["PreToolUse"][0]
    check("copilot hooks version", hook["version"], COPILOT_HOOKS_VERSION)
    check("copilot hook host", "BOSSA_HOST=copilot" in entry["bash"], True)
    check("copilot hook bash fails open", "exit 0" in entry["bash"], True)
    check("copilot hook powershell", "py -3" in entry["powershell"], True)
    check("copilot hook powershell fails open", "exit 0" in entry["powershell"], True)
    check("copilot hook timeout", entry["timeoutSec"], HOOK_TIMEOUT_SECONDS)

    check("codex hooks file exists", (ROOT / codex["hooks"]).is_file(), True)
    codex_entry = _load_json(ROOT / codex["hooks"])["hooks"]["PreToolUse"][0]
    check("codex hook host", "BOSSA_HOST=codex" in codex_entry["hooks"][0]["command"], True)
    check("codex hook timeout", codex_entry["hooks"][0]["timeout"], HOOK_TIMEOUT_SECONDS)


def _check_copilot(check: Callable[[str, object, object], None]) -> None:
    """Check every copilot/agents file: frontmatter fields, tool aliases, body, size."""
    agents = claude_agents()
    found = sorted(p.name for p in COPILOT_AGENTS.glob("*"))
    check("copilot agent files", found, sorted(n + COPILOT_SUFFIX for n in agents))
    for name, (front_claude, claude_body) in agents.items():
        path = COPILOT_AGENTS / (name + COPILOT_SUFFIX)
        front, body = parse_frontmatter(path.read_text(encoding="utf-8"), as_json=True)
        check(name + " copilot name", front.get("name"), name)
        check(name + " copilot description", front.get("description"), front_claude["description"])
        tools = front.get("tools")
        check(name + " copilot tools valid", all(t in COPILOT_ALIASES for t in tools), True)
        check(name + " copilot tools", tools, COPILOT_TOOLS[name])
        check(name + " copilot instructions flag", front.get("include-custom-instructions"),
              None if name == ARCHITECT else True)
        check(name + " copilot body", body, copilot_body(name, claude_body))
        check(name + " copilot body size", len(body) < COPILOT_PROMPT_LIMIT, True)


def _check_codex(check: Callable[[str, object, object], None]) -> None:
    """Check codex/AGENTS.md and every codex/agents TOML file."""
    agents = claude_agents()
    doc = CODEX_DOC.read_text(encoding="utf-8")
    check("codex AGENTS.md", doc, codex_doc_text(agents[ARCHITECT][1]))
    check("codex AGENTS.md size", len(doc.encode("utf-8")) < CODEX_DOC_LIMIT, True)
    if sys.version_info < TOML_MIN_VERSION:
        print("check_hosts: skipping TOML checks (needs Python 3.11+)")
        return
    import tomllib

    workers = sorted(n for n in agents if n != ARCHITECT)
    check("codex agent files", sorted(p.name for p in CODEX_AGENTS.glob("*")),
          [n + ".toml" for n in workers])
    for name in workers:
        data = tomllib.loads((CODEX_AGENTS / (name + ".toml")).read_text(encoding="utf-8"))
        check(name + " toml name", data.get("name"), name)
        front_claude, claude_body = agents[name]
        check(name + " toml description", data.get("description"), front_claude["description"])
        instructions = data.get("developer_instructions")
        check(name + " toml body", instructions, codex_body(name, claude_body))
        check(name + " toml sandbox", data.get("sandbox_mode"),
              "read-only" if name in CODEX_READ_ONLY else None)
        check(name + " toml model unset", "model" in data, False)


def selftest() -> int:
    """Parse every host file, compare generated agents to their sources and report the count."""
    failures = []  # type: List[str]
    count = [0]

    def check(name: str, got: object, want: object) -> None:
        count[0] += 1
        if got != want:
            failures.append("FAIL %s: want %r, got %r" % (name, want, got))

    for group in (_check_manifests, _check_copilot, _check_codex):
        try:
            group(check)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            failures.append("FAIL %s: %s: %s" % (group.__name__, type(error).__name__, error))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return EXIT_FAILED
    print("bossa check_hosts selftest: %d checks passed" % count[0])
    return EXIT_OK


def main(argv: List[str]) -> int:
    """Run --write or --selftest."""
    if "--write" in argv[1:]:
        return write_all()
    if "--selftest" in argv[1:]:
        return selftest()
    print("usage: check_hosts.py --write | --selftest", file=sys.stderr)
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv))

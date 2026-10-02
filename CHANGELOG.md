# Changelog

## 0.3.0 - 2026-10-01

- Copilot CLI plugin: `copilot plugin install bossa@bossa` brings the architect and the six workers as `.agent.md` files, generated from the Claude agents so the prompt text has one source, plus the destructive-git guard. The Copilot architect has read and search tools only.
- Codex CLI copy-in: `codex/AGENTS.md` carries the architect rules and `codex/agents/*.toml` the six workers, because Codex plugins cannot ship agents. A Codex plugin manifest ships the guard hook, which you trust once with `/hooks`.
- Guard host mode: `BOSSA_HOST=copilot` or `codex` applies only the destructive-git rule and prints the host's deny JSON, since those hosts name no agent. `hooks/check_hosts.py --selftest` validates every host file and keeps it in step with `agents/*.md`.

## 0.2.0 - 2026-10-01

- Companion plugins: caveman and ponytail are offered from the bossa marketplace, installed with `/plugin install caveman@bossa` and `/plugin install ponytail@bossa`.
- Worker report hook: a SubagentStart hook asks every bossa worker for a terse report that leads with status, files, tests and risks. It skips the architect, and `BOSSA_WORKER_STYLE=0` turns it off.
- `/bossa:stats` reports how the latest sessions' tokens split between the main session and each worker type. It measures where tokens went and claims no saving.

## 0.1.0 - 2026-10-01

- Architect main session and six worker subagents: scout, implementer, hard-implementer, code-reviewer, security-reviewer and git-ops.
- Guard hook that blocks destructive git for everyone, reserves mutating git for git-ops, and keeps the architect to read-only commands.
- Marketplace manifest so the plugin installs with `/plugin install bossa@bossa`.

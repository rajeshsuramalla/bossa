# Changelog

## 0.2.0 - 2026-10-01

- Companion plugins: caveman and ponytail are offered from the bossa marketplace, installed with `/plugin install caveman@bossa` and `/plugin install ponytail@bossa`.
- Worker report hook: a SubagentStart hook asks every bossa worker for a terse report that leads with status, files, tests and risks. It skips the architect, and `BOSSA_WORKER_STYLE=0` turns it off.
- `/bossa:stats` reports how the latest sessions' tokens split between the main session and each worker type. It measures where tokens went and claims no saving.

## 0.1.0 - 2026-10-01

- Architect main session and six worker subagents: scout, implementer, hard-implementer, code-reviewer, security-reviewer and git-ops.
- Guard hook that blocks destructive git for everyone, reserves mutating git for git-ops, and keeps the architect to read-only commands.
- Marketplace manifest so the plugin installs with `/plugin install bossa@bossa`.

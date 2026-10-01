# Changelog

## 0.1.0 - 2026-10-01

- Architect main session and six worker subagents: scout, implementer, hard-implementer, code-reviewer, security-reviewer and git-ops.
- Guard hook that blocks destructive git for everyone, reserves mutating git for git-ops, and keeps the architect to read-only commands.
- Marketplace manifest so the plugin installs with `/plugin install bossa@bossa`.

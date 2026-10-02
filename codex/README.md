# bossa on Codex CLI

Codex plugins can ship skills, MCP servers and hooks, but not agents or an `AGENTS.md`. So
the architect rules and the six workers are copy-in files here, and the plugin carries only
the git guard hook.

## Install

1. Hook: `codex plugin marketplace add rajeshsuramalla/bossa`, then run `/plugins` in the Codex
   TUI, open the bossa tab and install. It needs `python3`, `python` or `py -3` and a POSIX `sh`.
2. Trust the hook: Codex skips plugin hooks until you review them. Run `/hooks` in Codex
   and trust the bossa entry.
3. Architect rules: copy `codex/AGENTS.md` to your repo root, or to `~/.codex/AGENTS.md` for
   every project. If you already have an `AGENTS.md`, append its text instead.
4. Workers: copy `codex/agents/*.toml` into `.codex/agents/` in your repo, or into
   `~/.codex/agents/`. Each file has a commented `# model = ...` line; set a model name
   your account offers, or leave it to inherit the session model.
5. Start Codex and ask for work. The rules tell the architect to spawn each worker by name.

Worker prompts name `CLAUDE.md` for project rules. Keep one, or tell the architect where
yours live.

## Fidelity gaps

1. The architect is an instruction file, not a launched agent. It shapes every session in
   the repo (or every session, from `~/.codex`), and the Codex docs do not say whether the
   workers also read it.
2. The guard blocks destructive git only. A Codex `PreToolUse` payload names no agent, so
   "only git-ops commits" and the architect's read-only shell are instructions, not enforced.
3. Models are not pinned and `/bossa:stats` does not exist here. The files were validated
   structurally only (`python3 hooks/check_hosts.py --selftest`), never run in Codex.

Known risk: Codex subagents run in the same repo and may load the root `AGENTS.md`, so workers
could read the architect's "never edit code" rule. If a worker refuses to edit, move the
architect rules to `~/.codex/AGENTS.md` for the architect session only, or keep them in a profile.

After editing `agents/*.md`, regenerate these files with `python3 hooks/check_hosts.py --write`.

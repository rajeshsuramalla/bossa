# bossa

bossa is a Claude Code plugin that runs your main session as an architect: it
designs, delegates and decides, and never writes code or changes git state. Six
worker subagents do the work, and git-ops owns every branch, commit and pull
request. The saving is the architect's context, not the model tier: it only
ever reads specs and review findings, while the workers read the files and run
the tests. A PreToolUse hook enforces the boundary, not the prompt.

## Install

```
/plugin marketplace add rajeshsuramalla/bossa
/plugin install bossa@bossa
/plugin install caveman@bossa
/plugin install ponytail@bossa
```

Recommended set: bossa, caveman (terse main-session output) and ponytail
(smallest working change). caveman and ponytail entries track their upstream
repos; bossa does not pin them.

To try it from a local checkout: `claude --plugin-dir ./bossa`. The hooks and
`/bossa:stats` need `python3`, `python` or `py -3` (3.8+), and on Windows Git
Bash: hooks cannot run under PowerShell alone. git-ops uses `git` and `gh`.
Auto-update is off for third-party marketplaces: run `/plugin marketplace
update bossa` then `claude plugin update bossa@bossa`, or turn it on under
`/plugin` -> Marketplaces. A release is a `version` bump in `plugin.json`.

## Launch as the architect

A plugin may ship a `settings.json` that sets `"agent"`, but bossa does not:
that would make every session an architect session. Start it on purpose with
`claude --agent bossa:architect`, or per project with
`{"agent": "bossa:architect"}` in `.claude/settings.json`. `--agent` overrides
it for one session. The bare name `architect` also works unless another agent
has that name.

## How a ticket flows

1. The architect reads your request, asks about anything ambiguous, and has
   `scout` answer factual questions. git-ops creates the ticket branch.
2. It splits the work into one-concern tasks and writes a spec for each, using
   the template below. `implementer` builds routine tasks, `hard-implementer`
   the hard ones and anything the implementer failed twice.
3. `code-reviewer` checks every finished task against its spec, plus
   `security-reviewer` when the diff touches a trust boundary. The architect
   decides which findings are valid and sends numbered corrections back.
4. After review passes, git-ops commits the listed files, one commit per task.
   It pushes and opens a pull request only when you ask. It never merges.

### Stats

`/bossa:stats` reads Claude Code's transcripts for the project and prints, for
the latest five sessions, main-session tokens, worker tokens per agent type and
the main session's share, each reply counted once. It claims no saving: without
a run of the same ticket without bossa to compare against, a "% saved" would be
invented. Cache reads dominate, so read it as context carried, not cost.

## Who does what

| Agent | Job | Model |
| --- | --- | --- |
| `architect` | Main session. Plans, specs, decides. Read-only Bash. | opus |
| `scout` | Finds code, traces call paths, runs tests and builds, reads logs. | sonnet |
| `implementer` | Routine specs: CRUD, wiring, tests, renames, simple fixes. | sonnet |
| `hard-implementer` | Concurrency, caching, algorithms, contract changes, security-sensitive code. | opus |
| `code-reviewer` | Reviews every finished diff before commit. | opus |
| `security-reviewer` | Reviews diffs that touch auth, input, queries, paths, secrets, crypto, dependencies. | opus |
| `git-ops` | Every branch, stage, commit, push, pull request, rebase, tag. | sonnet |

## Spec template

Every task spec has this shape; the Ladder line pairs with ponytail:

```
Goal: one sentence.
Ladder: the rung this task stops at, and what to reuse: an existing helper,
  a stdlib call, a native platform feature or an installed dependency.
Context: files and symbols to read first, with paths.
Changes: numbered, each naming the file and the behaviour.
Interfaces: exact signatures, types, routes or schemas.
Constraints: patterns to follow, things not to touch. No new dependency
  unless the Ladder line names it.
Acceptance: commands to run and the expected result. Name one case that
  passes on HEAD and must still pass.
Out of scope: what to leave alone.
```

## The guard

`hooks/architect_guard.py` runs before every Bash and Agent call: exit 2 blocks
with a reason on stderr, and unreadable input fails open.

- Every caller: no `push --force`, `-f`, `+ref` or `--mirror`, no `reset --hard`,
  no `clean`, no `--no-verify`.
- Mutating git (`add`, `commit`, `push`, `rebase`, `merge`, `checkout`,
  `stash`, `tag`, `reset`, `worktree` and similar) is blocked, by subcommand,
  for bossa's own agents except `git-ops`; read-only `git stash list`, `git tag
  -l` and `git worktree list` are blocked for workers too. A user's own agents
  named scout, implementer, hard-implementer, code-reviewer, security-reviewer
  or git-ops are covered; other agents and agentless sessions are not.
- The architect as main session: one plain command that starts with `git
  status`, `git diff`, `git log`, `git show`, `git blame`, `ls` or `pwd`. No
  chaining, pipes, redirection or substitution.
- The architect cannot upgrade a worker to opus on an Agent call.

## Tested

A live `claude -p --agent bossa:architect` run on Claude Code 2.1.287 showed
the architect spawn `bossa:scout` through the scoped allowlist and the guard
block a piped Bash call; `/bossa:stats` ran live too. Only validated or fed
stdin: the companion installs (`caveman@bossa`, `ponytail@bossa`) and the
SubagentStart hook. Only `--selftest` covers worker git blocks, `git-ops` and
reviewer spawns, and a bare `architect` agent type.

## Pairing with caveman and ponytail

bossa ships its own worker report hook (workers only), so caveman only styles
the main session. ponytail injects its full rules into every subagent unless
`PONYTAIL_SUBAGENT_MATCHER` is set in project settings `env`, e.g.
`implementer|hard-implementer` (unanchored, so it matches `bossa:implementer`).

## What to put in your project's CLAUDE.md

The architect and every worker read it, so project knowledge goes there:
- Invariants that must never change, and the tests that guard them.
- The exact commands to run tests, lint, format and build.
- Protected or generated paths, trust boundaries, and any branch or commit
  conventions that differ from the defaults.

## Limits

- A plugin cannot ship `env` or most settings; set `CLAUDE_CODE_SUBAGENT_MODEL`
  in your project settings. bossa workers pin their own `model`, which outranks
  it, so it only affects other subagents.
- `code-reviewer` keeps `memory: project`, stored per project under
  `.claude/agent-memory/`. Nothing carries over between projects.
- Plugin agents ignore `permissionMode`, `hooks` and `mcpServers`, so the
  guard hook is the only enforcement. Without a working Python, `py.sh` exits 1
  and Claude Code reports a hook error, but nothing is blocked.
- The guard matches command text. It does not parse `bash -c`, `eval` or
  wrappers that take options, such as `env -i` or `sudo -u`.
- `git commit -n` (short form of `--no-verify`) is not caught; the long form is.
- `BOSSA_WORKER_STYLE=0` in your environment or `env` turns off the worker hook.
- `/bossa:stats` reads the session's current directory: run it at the project root.

## Licence

MIT. See `LICENSE`. Copyright 2026 Rajesh Suramalla.

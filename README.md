# bossa

bossa is a Claude Code plugin that runs your main session as an architect.
The architect designs, delegates and decides. It never writes code and never
changes git state. Six worker subagents do the work: a scout reads and runs
things, two implementers write code, two reviewers check it, and git-ops owns
every branch, commit and pull request. The saving is the architect's context,
not the model tier: it only ever reads specs and review findings, while the
workers read the files and run the tests. A PreToolUse hook enforces the
boundary instead of leaving it to the prompt.

## Install

```
/plugin marketplace add rajeshsuramalla/bossa
/plugin install bossa@bossa
```

To try it from a local checkout: `claude --plugin-dir ./bossa`. The guard hook
needs `python3`, `python` or `py -3` (3.8 or newer). On Windows it needs Git
Bash: hooks cannot run under PowerShell alone. git-ops uses `git` and `gh`.

### Updating

Auto-update is off by default for third-party marketplaces. Run `/plugin
marketplace update bossa`, then `claude plugin update bossa@bossa` (or Update
now on the Installed tab of `/plugin`), or turn on auto-update under `/plugin`
-> Marketplaces -> bossa. A new release is a `version` bump in `plugin.json`.

## Launch as the architect

A plugin may ship a `settings.json` that sets `"agent"`, but bossa does not: it
would make every session in every project an architect session. Start it on
purpose with `claude --agent bossa:architect`, or per project in
`.claude/settings.json`:

```json
{
  "agent": "bossa:architect"
}
```

`--agent` overrides the setting for one session. The bare name `architect`
also works while no other agent of that name exists.

## How a ticket flows

1. The architect reads your request, asks about anything ambiguous, and has
   `scout` answer factual questions. git-ops creates the ticket branch.
2. It splits the work into one-concern tasks and writes a spec for each, using
   the template below.
3. `implementer` builds routine tasks, `hard-implementer` the hard ones and
   anything the implementer failed twice.
4. `code-reviewer` checks every finished task against its spec, plus
   `security-reviewer` when the diff touches a trust boundary. The architect
   decides which findings are valid and sends numbered corrections back.
5. After review passes, git-ops commits the listed files, one commit per task.
   It pushes and opens a pull request only when you ask. It never merges.

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

`hooks/architect_guard.py` runs before every Bash and Agent call. It exits 2
with a reason on stderr to block, and fails open if its input cannot be read.
`python3 hooks/architect_guard.py --selftest` runs its built-in cases.

- Every caller: no `push --force`, `-f`, `+ref` or `--mirror`, no `reset --hard`,
  no `clean`, no `--no-verify`.
- Mutating git (`add`, `commit`, `push`, `rebase`, `merge`, `checkout`, `stash`,
  `tag`, `reset`, `worktree` and similar) is blocked for bossa's own agents
  except `git-ops`, by subcommand: read-only `git stash list`, `git tag -l` and
  `git worktree list` are blocked for workers too. That covers a user's own
  agents named scout, implementer, hard-implementer, code-reviewer,
  security-reviewer or git-ops. Other agents and agentless sessions are not
  affected.
- The architect as main session: one plain command that starts with `git
  status`, `git diff`, `git log`, `git show`, `git blame`, `ls` or `pwd`. No
  chaining, pipes, redirection or substitution.
- The architect may not upgrade a worker to opus on an Agent call; workers run
  on their frontmatter model.

## Tested

A live `claude -p --agent bossa:architect` run on Claude Code 2.1.287 showed
two things: the architect spawns `bossa:scout` through the scoped allowlist,
and the guard runs in that main session and blocks a piped Bash call. Worker
git blocks, `git-ops` and reviewer spawns, and the guard's handling of a bare
`architect` agent type are covered by `--selftest` only.

## Pairing with caveman and ponytail

bossa ships no SubagentStart hook. To scope ponytail's to the workers, set
`PONYTAIL_SUBAGENT_MATCHER` to `implementer|hard-implementer|code-reviewer` in
your project settings `env`; the unanchored regex also matches `bossa:implementer`.
Caveman-style worker reports need a SubagentStart hook of your own.

## What to put in your project's CLAUDE.md

The architect and every worker read it, so project knowledge goes there:
- Invariants that must never change, and the tests that guard them.
- The exact commands to run tests, lint, format and build.
- Which paths are protected or generated, and what counts as a trust boundary.
- Branch and commit conventions, if they differ from the defaults.

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

## Licence

MIT. See `LICENSE`. Copyright 2026 Rajesh Suramalla.

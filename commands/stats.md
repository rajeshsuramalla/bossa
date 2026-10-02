---
description: Show how recent session tokens split between the architect and the workers
allowed-tools: Bash("${CLAUDE_PLUGIN_ROOT}/hooks/py.sh" stats.py)
---

!`"${CLAUDE_PLUGIN_ROOT}/hooks/py.sh" stats.py`

Show the output above to the user exactly as printed, table and the note line under it, then one sentence naming the session with the lowest main share. Say nothing else; make no claim about savings. If no table appears, repeat the error line to the user.

#!/usr/bin/env python3
"""Report how a project's recent Claude Code sessions split tokens between main and workers.

Reads the transcripts Claude Code keeps under its projects directory: one JSONL file per session
plus one per subagent in <session>/subagents/, whose agent-<id>.meta.json names the agent type.
Tokens are input + cache read + cache creation + output, taken from message.usage on assistant
records. It measures where tokens went; it makes no claim about what a different setup would use.
"""
import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

EXIT_OK = 0
EXIT_NO_SESSIONS = 1
EXIT_SELFTEST_FAILED = 1

DEFAULT_SESSIONS = 5
CONFIG_DIR_VARIABLE = "CLAUDE_CONFIG_DIR"
DEFAULT_CONFIG_DIR = ".claude"
ARCHITECT_SETTINGS = ("architect", "bossa:architect")
UNKNOWN_AGENT_TYPE = "unknown"
SHORT_ID_LENGTH = 8
STARTED_LENGTH = len("YYYY-MM-DDTHH:MM")
INPUT_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
OUTPUT_KEY = "output_tokens"
NOTE = (
    "tokens = input + cache read + cache write + output per reply; cache reads dominate and "
    "bill at a lower rate; this measures context carried per turn, not cost"
)
TEXT_COLUMNS = 3
HEADER = (
    "SESSION",
    "STARTED (UTC)",
    "MAIN AS",
    "MAIN",
    "MAIN OUT",
    "WORKERS",
    "WORKERS OUT",
    "MAIN SHARE",
)


@dataclass
class Tally:
    """Token counts, and how many transcripts were merged into them."""

    total: int = 0
    output: int = 0
    agents: int = 0

    def add(self, other: "Tally") -> None:
        self.total += other.total
        self.output += other.output
        self.agents += other.agents


def encode_project(path: str) -> str:
    """Return Claude Code's directory name for a project: non-alphanumerics become '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def locate_projects_dir(project: Path, config_dir: Path) -> Optional[Path]:
    """Return the transcript directory for a project, or None when it does not exist."""
    for candidate in (os.path.abspath(project), os.path.realpath(project)):
        found = config_dir / "projects" / encode_project(candidate)
        if found.is_dir():
            return found
    return None


def _count(value: object) -> int:
    return value if isinstance(value, int) else 0


def _usage(record: dict) -> Optional[Tuple[object, Tally]]:
    """Return (message key, tokens) for an assistant record that carries usage, else None."""
    message = record.get("message")
    if record.get("type") != "assistant" or not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    output = _count(usage.get(OUTPUT_KEY))
    total = output + sum(_count(usage.get(key)) for key in INPUT_KEYS)
    return message.get("id"), Tally(total=total, output=output)


def _scan(lines: Iterable[str]) -> Tuple[Tally, str, bool]:
    """Sum transcript lines: tokens, first timestamp, and whether it ran as the architect."""
    by_message: Dict[object, Tally] = {}
    started = ""
    architect = False
    for number, line in enumerate(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue  # a live session can be mid-write, so a torn line is expected
        if not isinstance(record, dict):
            continue
        started = started or str(record.get("timestamp") or "")
        if record.get("type") == "agent-setting":
            architect = architect or record.get("agentSetting") in ARCHITECT_SETTINGS
        found = _usage(record)
        if found:
            # A reply split over several records repeats the same usage under one message id.
            by_message[found[0] or ("line", number)] = found[1]
    tally = Tally(agents=1)
    for part in by_message.values():
        tally.add(part)
    return tally, started, architect


def read_transcript(path: Path) -> Tuple[Tally, str, bool]:
    """Stream one transcript line by line and sum it."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return _scan(handle)
    except OSError as error:
        print("stats: cannot read %s: %s" % (path, error), file=sys.stderr)
        return Tally(), "", False


def agent_type(transcript: Path) -> str:
    """Read the agent type from the transcript's sibling meta file."""
    meta = transcript.with_suffix(".meta.json")
    try:
        value = json.loads(meta.read_text(encoding="utf-8")).get("agentType")
    except (OSError, ValueError, AttributeError):
        return UNKNOWN_AGENT_TYPE
    return value if isinstance(value, str) and value else UNKNOWN_AGENT_TYPE


def _share(main: int, workers: int) -> Optional[float]:
    return round(100.0 * main / (main + workers), 1) if main + workers else None


def _row(session: str, started: str, role: str, main: Tally, workers: Dict[str, Tally]) -> dict:
    worker_total = Tally()
    for tally in workers.values():
        worker_total.add(tally)
    return {
        "session": session,
        "started": started,
        "main_as": role,
        "main": {"total": main.total, "output": main.output},
        "workers_total": {"total": worker_total.total, "output": worker_total.output},
        "workers": {
            kind: {"total": t.total, "output": t.output, "agents": t.agents}
            for kind, t in sorted(workers.items())
        },
        "main_share_pct": _share(main.total, worker_total.total),
    }


def read_session(main_path: Path) -> dict:
    """Sum a session's main transcript and its subagent transcripts, grouped by agent type."""
    main, started, architect = read_transcript(main_path)
    workers: Dict[str, Tally] = {}
    for transcript in sorted((main_path.with_suffix("") / "subagents").glob("agent-*.jsonl")):
        workers.setdefault(agent_type(transcript), Tally()).add(read_transcript(transcript)[0])
    role = "architect" if architect else "main"
    return _row(main_path.stem, started, role, main, workers)


def collect(projects_dir: Path, sessions: int) -> dict:
    """Report the latest sessions, newest first, and their totals."""
    dated = []
    for path in projects_dir.glob("*.jsonl"):
        try:
            dated.append((path.stat().st_mtime, path))
        except FileNotFoundError:
            continue  # the session file was removed after the directory was listed
    newest = [path for _, path in sorted(dated, key=lambda item: item[0], reverse=True)]
    rows = [read_session(path) for path in newest[:sessions]]
    main = Tally()
    workers: Dict[str, Tally] = {}
    for row in rows:
        main.add(Tally(row["main"]["total"], row["main"]["output"]))
        for kind, w in row["workers"].items():
            workers.setdefault(kind, Tally()).add(Tally(w["total"], w["output"], w["agents"]))
    totals = _row("total", "", "", main, workers)
    totals["sessions"] = len(rows)
    return {"note": NOTE, "sessions": rows, "totals": totals}


def _number(value: int) -> str:
    return "{:,}".format(value)


def _line(label: str, started: str, role: str, row: dict) -> Tuple[str, ...]:
    share = row["main_share_pct"]
    return (
        label, started, role,
        _number(row["main"]["total"]), _number(row["main"]["output"]),
        _number(row["workers_total"]["total"]), _number(row["workers_total"]["output"]),
        "n/a" if share is None else "%.1f%%" % share,
    )


def render_table(report: dict) -> str:
    """Format the report as a plain table: totals row, then the one-line note."""
    rows: List[Tuple[str, ...]] = [HEADER]
    for row in report["sessions"]:
        started = row["started"][:STARTED_LENGTH].replace("T", " ")
        rows.append(_line(row["session"][:SHORT_ID_LENGTH], started, row["main_as"], row))
        for kind, w in row["workers"].items():
            label = "  %s x%d" % (kind, w["agents"])
            rows.append((label, "", "", "", "", _number(w["total"]), _number(w["output"]), ""))
    totals = report["totals"]
    count = totals["sessions"]
    label = "TOTAL (%d session%s)" % (count, "" if count == 1 else "s")
    rows.append(_line(label, "", "", totals))
    widths = [max(len(r[i]) for r in rows) for i in range(len(HEADER))]

    def format_row(row: Tuple[str, ...]) -> str:
        cells = [
            c.ljust(w) if i < TEXT_COLUMNS else c.rjust(w)
            for i, (c, w) in enumerate(zip(row, widths))
        ]
        return "  ".join(cells).rstrip()

    return "\n".join([format_row(r) for r in rows] + [report["note"]])


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Token split between main session and workers.")
    parser.add_argument("--project", default=os.getcwd(), help="project directory (default: cwd)")
    parser.add_argument(
        "--sessions", type=int, default=DEFAULT_SESSIONS, help="latest sessions to read"
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--selftest", action="store_true", help="run the built-in cases")
    args = parser.parse_args(argv)
    if args.sessions < 1:
        parser.error("--sessions must be at least 1")
    return args


def main(argv: List[str]) -> int:
    """Print the token split for a project's latest sessions."""
    args = parse_args(argv[1:])
    if args.selftest:
        return selftest()
    config_dir = Path(os.environ.get(CONFIG_DIR_VARIABLE) or Path.home() / DEFAULT_CONFIG_DIR)
    projects_dir = locate_projects_dir(Path(args.project), config_dir)
    report = collect(projects_dir, args.sessions) if projects_dir else None
    if not report or not report["sessions"]:
        expected = config_dir / "projects" / encode_project(os.path.abspath(args.project))
        print(
            "stats: no Claude Code sessions found for %s (looked in %s)"
            % (args.project, projects_dir or expected),
            file=sys.stderr,
        )
        return EXIT_NO_SESSIONS
    print(json.dumps(report, indent=2) if args.json else render_table(report))
    return EXIT_OK


def _write(path: Path, records: List[object], torn: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + torn, encoding="utf-8")


def _reply(message_id: str, inp: int, read: int, created: int, out: int) -> dict:
    usage = {
        "input_tokens": inp,
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": created,
        "output_tokens": out,
    }
    return {"type": "assistant", "message": {"id": message_id, "usage": usage}}


def _fake_projects(root: Path) -> None:
    """Two sessions: A (architect, two subagents, a duplicated reply) newer than B (torn line)."""
    name = encode_project(os.path.abspath(root / "proj"))
    projects = root / DEFAULT_CONFIG_DIR / "projects" / name
    first = {"type": "user", "timestamp": "2026-09-30T10:00:00.000Z", "message": {"role": "user"}}
    older = {**first, "timestamp": "2026-09-29T08:30:00.000Z"}
    architect = {"type": "agent-setting", "agentSetting": "architect"}
    replies = [_reply("m1", 10, 100, 1000, 50), _reply("m1", 10, 100, 1000, 50)]
    records = [architect, first] + replies + [_reply("m2", 1, 2, 3, 4)]
    _write(projects / "aaaaaaaa-1111.jsonl", records)
    workers = (("a1", "scout", (5, 0, 0, 5)), ("a2", "bossa:implementer", (100, 0, 0, 20)))
    for agent, kind, tokens in workers:
        sub = projects / "aaaaaaaa-1111" / "subagents"
        _write(sub / ("agent-%s.jsonl" % agent), [_reply("s-" + agent, *tokens)])
        (sub / ("agent-%s.meta.json" % agent)).write_text(json.dumps({"agentType": kind}))
    torn = '{"type": "assistant", "message": {"id": "b2", "usage": {"input_tok'
    _write(projects / "bbbbbbbb-2222.jsonl", [older, _reply("b1", 7, 0, 0, 3)], torn=torn)
    os.utime(projects / "aaaaaaaa-1111.jsonl", (2000, 2000))
    os.utime(projects / "bbbbbbbb-2222.jsonl", (1000, 1000))


def _run(argv: List[str]) -> Tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["stats.py"] + argv)
    return code, out.getvalue(), err.getvalue()


def _selftest_checks(root: Path, check: Callable[[str, object, object], None]) -> None:
    project = str(root / "proj")
    code, out, _ = _run(["--project", project, "--json"])
    report = json.loads(out)
    a, b = report["sessions"]
    totals = report["totals"]
    check("exit code", code, EXIT_OK)
    check("newest first", (a["session"], b["session"]), ("aaaaaaaa-1111", "bbbbbbbb-2222"))
    check("duplicate and no-usage records skipped", a["main"], {"total": 1170, "output": 54})
    check("architect marker", (a["main_as"], b["main_as"]), ("architect", "main"))
    check(
        "workers grouped by type",
        a["workers"],
        {
            "bossa:implementer": {"total": 120, "output": 20, "agents": 1},
            "scout": {"total": 10, "output": 5, "agents": 1},
        },
    )
    check("main share", a["main_share_pct"], 90.0)
    check(
        "torn line skipped, no workers",
        (b["main"], b["workers"], b["main_share_pct"]),
        ({"total": 10, "output": 3}, {}, 100.0),
    )
    check(
        "started",
        (a["started"], b["started"]),
        ("2026-09-30T10:00:00.000Z", "2026-09-29T08:30:00.000Z"),
    )
    check(
        "totals",
        (totals["main"], totals["workers_total"], totals["main_share_pct"], totals["sessions"]),
        ({"total": 1180, "output": 57}, {"total": 130, "output": 25}, 90.1, 2),
    )
    newest = json.loads(_run(["--project", project, "--sessions", "1", "--json"])[1])
    kept = [s["session"] for s in newest["sessions"]]
    check("--sessions 1 keeps the newest", kept, ["aaaaaaaa-1111"])
    table = _run(["--project", project])[1].splitlines()
    check("table totals row", table[-2].split()[:3], ["TOTAL", "(2", "sessions)"])
    check("table footer and json note", (table[-1], report["note"]), (NOTE, NOTE))
    kinds = [line.split()[0] for line in table[2:4]]
    check("table lists worker types", kinds, ["bossa:implementer", "scout"])
    code, _, err = _run(["--project", str(root / "elsewhere")])
    missing = (code, "no Claude Code sessions" in err)
    check("missing projects dir", missing, (EXIT_NO_SESSIONS, True))
    dangling = root / DEFAULT_CONFIG_DIR / "projects" / encode_project(os.path.abspath(project))
    try:
        (dangling / "cccccccc-3333.jsonl").symlink_to(root / "gone.jsonl")
    except (OSError, NotImplementedError):
        return  # no symlink support here, so the vanished-file case cannot be built
    count = len(json.loads(_run(["--project", project, "--json"])[1])["sessions"])
    check("vanished session file skipped", count, 2)


def selftest() -> int:
    """Build fake transcripts in a temp dir and check the computed numbers."""
    failures: List[str] = []
    cases = [0]

    def check(name: str, got: object, want: object) -> None:
        cases[0] += 1
        if got != want:
            failures.append("FAIL %s: want %r, got %r" % (name, want, got))

    saved = os.environ.get(CONFIG_DIR_VARIABLE)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_projects(root)
        os.environ[CONFIG_DIR_VARIABLE] = str(root / DEFAULT_CONFIG_DIR)
        try:
            _selftest_checks(root, check)
        finally:
            if saved is None:
                os.environ.pop(CONFIG_DIR_VARIABLE, None)
            else:
                os.environ[CONFIG_DIR_VARIABLE] = saved
        check("directory encoding", encode_project("/home/a.b/c_d-e"), "-home-a-b-c-d-e")
        check("locate misses cleanly", locate_projects_dir(root / "nope", root), None)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return EXIT_SELFTEST_FAILED
    print("bossa stats selftest: %d cases passed" % cases[0])
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))

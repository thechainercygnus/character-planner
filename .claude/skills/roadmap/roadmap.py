"""Edit the roadmap issue (#25) in one command, following CLAUDE.md's Roadmap rules.

Every command prints a diff of the issue body and changes nothing unless --save is given.
Needs only Python's standard library and an authenticated `gh`.

  python .claude/skills/roadmap/roadmap.py show [--section Next]
  python .claude/skills/roadmap/roadmap.py note 164 "PR #169 (ADR 0045)" [--save]
  python .claude/skills/roadmap/roadmap.py done 164 "#164 Own webhooks (PR #169, ADR 0045)" [--save]
  python .claude/skills/roadmap/roadmap.py add 170 "Title" "why it's here" --after 163 [--save]
  python .claude/skills/roadmap/roadmap.py replace 58 "- [ ] #58 New text" [--save]

An item is named by its issue number (164 or #164), or by a piece of its text when it has
no issue ("Fix: dialogs"); the piece must match exactly one open item.
"""

import argparse
import difflib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ISSUE = "25"


def fetch(body_file: str | None) -> str:
    if body_file:
        return Path(body_file).read_text(encoding="utf-8")
    # gh from PATH with fixed arguments: no untrusted input reaches the command.
    command = ["gh", "issue", "view", ISSUE, "--json", "body", "--jq", ".body"]
    result = subprocess.run(  # noqa: S603
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.replace("\r\n", "\n")


def save(body: str) -> None:
    # LF only: Windows Python would write CRLF in text mode.
    with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as handle:
        handle.write(body.encode("utf-8"))
        path = handle.name
    try:
        command = ["gh", "issue", "edit", ISSUE, "--body-file", path]
        subprocess.run(command, check=True)  # noqa: S603
    finally:
        Path(path).unlink(missing_ok=True)


def item_index(lines: list[str], key: str) -> int:
    """The line of the item key names: an open checklist line."""
    number = key.lstrip("#")
    if number.isdigit():
        pattern = re.compile(rf"^- \[[ x]\] #{number}\b")
        hits = [i for i, line in enumerate(lines) if pattern.match(line)]
    else:
        hits = [i for i, line in enumerate(lines) if line.startswith("- [") and key in line]
    if len(hits) != 1:
        found = "\n  ".join(lines[i] for i in hits) or "(none)"
        sys.exit(f"'{key}' matches {len(hits)} items, not one:\n  {found}")
    return hits[0]


def section_bounds(lines: list[str], title: str) -> tuple[int, int]:
    """The lines of a "## <title...>" section, heading excluded."""
    starts = [i for i, line in enumerate(lines) if line.startswith(f"## {title}")]
    if len(starts) != 1:
        sys.exit(f"no single section starting '## {title}'")
    start = starts[0] + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def note(lines: list[str], key: str, text: str) -> None:
    i = item_index(lines, key)
    line = lines[i].rstrip()
    lines[i] = f"{line} {text}" if line.endswith((".", ")")) else f"{line}. {text}"


def done(lines: list[str], key: str, summary: str) -> None:
    """Drop the item from its section and put the summary first in Done's list."""
    i = item_index(lines, key)
    del lines[i]
    start, end = section_bounds(lines, "Done")
    first = next((j for j in range(start, end) if lines[j].startswith("- ")), None)
    if first is None:
        lines.insert(start, f"- {summary}")
    else:
        lines[first] = f"- {summary}, {lines[first][2:]}"


def add(
    lines: list[str], number: str, title: str, why: str, after: str | None, section: str
) -> None:
    line = f"- [ ] #{number.lstrip('#')} {title}." + (f" {why}" if why else "")
    if after:
        lines.insert(item_index(lines, after) + 1, line)
        return
    start, end = section_bounds(lines, section)
    last = max((j for j in range(start, end) if lines[j].startswith("- [")), default=start - 1)
    lines.insert(last + 1, line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--save", action="store_true", help="write the change to the issue")
    parser.add_argument("--body-file", help="read the body from a file instead of GitHub (testing)")
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show")
    show.add_argument("--section")
    n = commands.add_parser("note", help="append text to an item: a PR number, a status")
    n.add_argument("item")
    n.add_argument("text")
    d = commands.add_parser("done", help="move an item to Done with a one-line summary")
    d.add_argument("item")
    d.add_argument("summary")
    a = commands.add_parser("add", help="add a new issue's line")
    a.add_argument("number")
    a.add_argument("title")
    a.add_argument("why", nargs="?", default="")
    a.add_argument("--after", help="the item it follows")
    a.add_argument("--section", default="Later", help="else the end of this section's list")
    r = commands.add_parser("replace", help="replace an item's whole line")
    r.add_argument("item")
    r.add_argument("line")
    args = parser.parse_args()

    before = fetch(args.body_file)
    lines = before.split("\n")
    if args.command == "show":
        if args.section:
            start, end = section_bounds(lines, args.section)
            print("\n".join(lines[start - 1 : end]))
        else:
            print(before)
        return
    if args.command == "note":
        note(lines, args.item, args.text)
    elif args.command == "done":
        done(lines, args.item, args.summary)
    elif args.command == "add":
        add(lines, args.number, args.title, args.why, args.after, args.section)
    elif args.command == "replace":
        lines[item_index(lines, args.item)] = args.line
    after = "\n".join(lines)
    diff = difflib.unified_diff(
        before.split("\n"), lines, "roadmap", "roadmap (new)", lineterm="", n=0
    )
    # Done is one long line: show its start, which is where changes go.
    shown = [line if len(line) <= 240 else line[:240] + " …" for line in diff]
    sys.stdout.buffer.write(("\n".join(shown) + "\n").encode("utf-8"))
    if args.save:
        save(after)
        print("saved")
    else:
        print("(dry run: add --save to write it)")


if __name__ == "__main__":
    main()

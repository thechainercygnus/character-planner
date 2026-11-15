---
name: roadmap
description: Read or edit the roadmap issue (#25) in one command, following CLAUDE.md's Roadmap rules. Use when picking the next item, noting a PR on an item's line, moving a merged or closed item to Done, or adding a new issue to the list.
---

# Roadmap (#25)

The roadmap is issue #25's body. CLAUDE.md's **Roadmap** section has the rules; this skill
is how to apply them without hand-editing the body.

All edits go through `roadmap.py`, next to this file. Every command prints a diff and
changes nothing until you add `--save`. Read the diff before saving.

```bash
python .claude/skills/roadmap/roadmap.py show                      # the whole body
python .claude/skills/roadmap/roadmap.py show --section Next       # one section
python .claude/skills/roadmap/roadmap.py note 164 "PR #169 (ADR 0045)."
python .claude/skills/roadmap/roadmap.py done 164 "#164 Own webhooks (PR #169, ADR 0045)"
python .claude/skills/roadmap/roadmap.py add 170 "Title" "Why it sits here." --after 163
python .claude/skills/roadmap/roadmap.py replace 58 "- [ ] #58 The whole new line"
```

Add `--save` once the diff is right. An item is named by its issue number, or by a piece
of its text when it has no issue (`"Fix: dialogs"`). The piece must match exactly one
checklist line.

## Which command when

| Event | Command |
|---|---|
| Choosing work | `show --section Next`, then `Later`. Take the first unchecked item that isn't parked or marked as Bryce's own. |
| A PR opened for an item | `note <issue> "PR #<n>."`, with the ADR if there is one |
| Its PR merged, more to do | `note <issue> "<what's left>"` |
| The issue closed | `done <issue> "<#n Title: one-line summary (PR #n, ADR n)>"`. It goes first in Done's list. |
| A new issue | `add <n> "<title>" "<one-line reason>" --after <n>` (or `--section Later`) |
| A fix with no issue | `add` doesn't fit: use `replace` on a nearby line, or write the line with `note` |

## Rules worth repeating
- Don't reorder items unless Bryce asks. Propose a reorder and wait for his answer.
- Don't change items you didn't work on.
- Keep the sections and their order. The script never moves sections.
- Close an issue only when its "Done when" is met, or when Bryce confirms a test he
  owns, as for #17 and #58. Close with `gh issue close <n> --comment "..."`, then `done`.
- Prose lines that aren't checklist items, such as "Nothing queued", aren't matched.
  Change those by hand: `show`, then `gh issue edit 25 --body-file <file>`, with the file
  written as LF bytes.

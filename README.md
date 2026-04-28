# dotbot-merge

Dotbot plugin that adds a `merge:` directive for generating files by concatenating source fragments.

## What it does

- Reads one or more source files relative to Dotbot's base directory.
- Concatenates them with a blank line between files.
- Writes the merged output to a target file.
- Supports dry-run, idempotent updates, conflict modes (`error`, `overwrite`, `backup`), and an optional output mode like `0444`.

> [!NOTE]  
> This plugin only supports unstructured text concatenation. It does not parse, merge, or validate structured formats like JSON, YAML, TOML, or XML.

## Installation

```shell
git submodule add https://github.com/seanniu/dotbot-merge
```

## Example

```yaml
- plugins:
    - dotbot-merge/

- defaults:
    merge:
      create: true
      conflict: backup
      mode: "0444"

- merge:
    merged/codex/AGENTS.md:
      - AGENTS.global.md
      - codex/AGENTS.md
    merged/claude/CLAUDE.md:
      - AGENTS.global.md
      - claude/CLAUDE.md

- link:
    ~/.codex/AGENTS.md: merged/codex/AGENTS.md
    ~/.claude/CLAUDE.md: merged/claude/CLAUDE.md
```

The plugin is implemented in `merge.py`.

## Conflict modes

- `error`: fail if the target exists and differs from the generated content
- `overwrite`: remove the target and write the new content
- `backup`: rename the target to `.dotbot-backup.<timestamp>` before writing

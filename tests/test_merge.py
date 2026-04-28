from argparse import Namespace
from pathlib import Path
from typing import Any, Dict, Optional

from dotbot.context import Context

from merge import Merge


def _plugin(
    base_directory: Path, *, defaults: Optional[Dict[str, Any]] = None, dry_run: bool = False
) -> Merge:
    context = Context(str(base_directory), options=Namespace(dry_run=dry_run))
    context.set_defaults({"merge": defaults or {}})
    return Merge(context)


def test_merge_joins_fragments_with_single_blank_line(tmp_path: Path) -> None:
    (tmp_path / "global.md").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "tool.md").write_text("beta\n", encoding="utf-8")
    target = tmp_path / "merged" / "output.md"

    plugin = _plugin(tmp_path, defaults={"create": True})

    assert plugin.handle("merge", {str(target): ["global.md", "tool.md"]}) is True
    assert target.read_text(encoding="utf-8") == "alpha\n\nbeta\n"


def test_merge_conflict_backup_creates_backup_and_rewrites_target(tmp_path: Path) -> None:
    (tmp_path / "global.md").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "tool.md").write_text("beta\n", encoding="utf-8")
    target = tmp_path / "output.md"
    target.write_text("old content\n", encoding="utf-8")

    plugin = _plugin(tmp_path, defaults={"conflict": "backup"})

    assert plugin.handle("merge", {str(target): ["global.md", "tool.md"]}) is True
    assert target.read_text(encoding="utf-8") == "alpha\n\nbeta\n"

    backups = list(tmp_path.glob("output.md.dotbot-backup.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "old content\n"


def test_merge_dry_run_does_not_write_or_backup_target(tmp_path: Path) -> None:
    (tmp_path / "global.md").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "tool.md").write_text("beta\n", encoding="utf-8")
    target = tmp_path / "output.md"
    target.write_text("old content\n", encoding="utf-8")

    plugin = _plugin(tmp_path, defaults={"conflict": "backup"}, dry_run=True)

    assert plugin.handle("merge", {str(target): ["global.md", "tool.md"]}) is True
    assert target.read_text(encoding="utf-8") == "old content\n"
    assert list(tmp_path.glob("output.md.dotbot-backup.*")) == []

"""
Dotbot plugin: ``merge`` directive.

Concatenates one or more source files (relative to the dotbot base directory)
into a single target file. Useful for composing per-tool config files out of a
shared "global" fragment plus tool-specific additions, e.g.::

    - merge:
        merged/codex/AGENTS.md:
          - AGENTS.global.md
          - codex/AGENTS.codex.md

Per-target options (all also accepted under ``defaults: merge:``):

    sources           list of source paths (required when using dict form)
    create            mkdir -p the target's parent dir (default: False)
    conflict          how to handle an existing target whose content differs:
                      ``error`` (default), ``overwrite``, or ``backup``
    ignore-missing    skip absent sources instead of failing (default: False)
    if                shell command; target is skipped unless it exits 0
    mode              octal string (e.g. "0444") applied via chmod after write

The plugin is idempotent: if the on-disk target already matches the planned
output, no write is performed and the run is a no-op for that target. Sources
are joined with a blank line, and the merged output always ends with a newline.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotbot.plugin import Plugin
from dotbot.util.common import shell_command


class Merge(Plugin):
    """Concatenates source files into a single target file."""

    supports_dry_run = True

    _directive = "merge"

    def can_handle(self, directive: str) -> bool:
        return directive == self._directive

    def handle(self, directive: str, data: Any) -> bool:
        if directive != self._directive:
            msg = f"Merge cannot handle directive {directive}"
            raise ValueError(msg)
        return self._process_merges(data)

    # ------------------------------------------------------------------ core

    def _process_merges(self, data: Any) -> bool:
        if not isinstance(data, dict):
            self._log.error("merge: expected a mapping of target -> sources/spec")
            return False

        defaults = self._context.defaults().get("merge", {}) or {}
        success = True

        for raw_target, spec in data.items():
            try:
                success &= self._process_one(raw_target, spec, defaults)
            except Exception as e:  # noqa: BLE001
                self._log.warning(f"merge: {raw_target}: unexpected error: {e!s}")
                success = False

        if success:
            self._log.info("All merges have been processed")
        else:
            self._log.error("Some merges were not successfully processed")
        return success

    def _process_one(self, raw_target: str, spec: Any, defaults: Dict[str, Any]) -> bool:
        # Resolve spec into a normalized options dict.
        opts = self._normalize_spec(spec, defaults)
        sources: List[str] = opts["sources"]
        if not sources:
            self._log.warning(f"merge: {raw_target}: no sources specified")
            return False

        # Gate on `if`.
        test_cmd: Optional[str] = opts.get("if")
        if test_cmd is not None and not self._test_success(test_cmd):
            self._log.info(f"Skipping merge {raw_target}")
            return True

        target_path = os.path.normpath(os.path.expandvars(os.path.expanduser(raw_target)))
        abs_target = os.path.abspath(target_path)

        # Read + assemble planned content.
        try:
            planned_bytes = self._build_content(sources, opts)
        except FileNotFoundError as e:
            self._log.warning(f"merge: {raw_target}: {e!s}")
            return False
        except OSError as e:
            self._log.warning(f"merge: {raw_target}: failed reading sources: {e!s}")
            return False

        dry = self._context.dry_run()

        # Ensure parent dir exists if `create`.
        if opts["create"] and not self._ensure_parent(abs_target, dry=dry):
            return False

        # Compare with existing target.
        existing_bytes = self._read_bytes_if_exists(abs_target)
        if existing_bytes is not None and existing_bytes == planned_bytes:
            # Still enforce mode even when content matches; this lets mode
            # changes applied after a previous install be corrected.
            mode_ok = self._enforce_mode(abs_target, opts.get("mode"), dry=dry)
            self._log.info(f"Merge up to date {raw_target} ({len(planned_bytes)} bytes)")
            return mode_ok

        # Content differs (or target missing).
        if existing_bytes is not None:
            conflict = opts["conflict"]
            if conflict == "backup":
                if not self._backup(abs_target, dry=dry):
                    return False
            elif conflict == "overwrite":
                if not self._unlink(abs_target, dry=dry):
                    return False
            elif conflict == "error":
                self._log.warning(
                    f"merge: {raw_target}: target exists and differs (set `conflict` to `overwrite` or `backup` to replace it)"
                )
                return False
            else:
                self._log.warning(
                    f"merge: {raw_target}: invalid conflict mode {conflict!r} (expected 'error', 'overwrite', or 'backup')"
                )
                return False

        # Write.
        if not self._write(abs_target, planned_bytes, raw_target=raw_target, dry=dry):
            return False

        # Apply mode.
        if not self._enforce_mode(abs_target, opts.get("mode"), dry=dry):
            return False

        return True

    # --------------------------------------------------------- option parsing

    def _normalize_spec(self, spec: Any, defaults: Dict[str, Any]) -> Dict[str, Any]:
        """Merge `defaults` (global) with per-target `spec` into a full opts dict."""
        opts: Dict[str, Any] = {
            "sources": [],
            "create": defaults.get("create", False),
            "conflict": defaults.get("conflict", "error"),
            "ignore-missing": defaults.get("ignore-missing", False),
            "if": defaults.get("if", None),
            "mode": defaults.get("mode", None),
        }

        if isinstance(spec, list):
            opts["sources"] = list(spec)
        elif isinstance(spec, dict):
            if "sources" in spec:
                opts["sources"] = list(spec["sources"])
            for key in ("create", "conflict", "ignore-missing", "if", "mode"):
                if key in spec:
                    opts[key] = spec[key]
        elif isinstance(spec, str):
            opts["sources"] = [spec]
        else:
            msg = f"merge: unsupported spec type {type(spec).__name__}"
            raise TypeError(msg)

        return opts

    # ------------------------------------------------------------- building

    def _build_content(self, sources: List[str], opts: Dict[str, Any]) -> bytes:
        base = self._context.base_directory()
        pieces: List[bytes] = []
        for src in sources:
            src_path = os.path.join(base, os.path.expandvars(src))
            if not os.path.exists(src_path):
                if opts["ignore-missing"]:
                    self._log.debug(f"merge: skipping missing source {src}")
                    continue
                msg = f"source not found: {src}"
                raise FileNotFoundError(msg)
            with open(src_path, "rb") as f:
                # Normalize fragment boundaries so a source's trailing newline
                # does not stack with the plugin's blank-line separator.
                pieces.append(f.read().rstrip(b"\r\n"))

        out = b"\n\n".join(pieces)
        if not out.endswith(b"\n"):
            out += b"\n"
        return out

    # ------------------------------------------------------------- filesystem

    def _read_bytes_if_exists(self, path: str) -> Optional[bytes]:
        if not os.path.lexists(path):
            return None
        if os.path.isdir(path) and not os.path.islink(path):
            self._log.warning(f"merge: target is a directory: {path}")
            # Return a sentinel value that will never match planned bytes so
            # the caller falls into the dirty branch; overwrite/backup will
            # still fail there because we can't rename a directory meaningfully.
            return b"\0<dotbot-merge: target is a directory>\0"
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as e:
            self._log.warning(f"merge: failed reading existing target {path}: {e!s}")
            return b"\0<dotbot-merge: unreadable>\0"

    def _ensure_parent(self, abs_target: str, *, dry: bool) -> bool:
        parent = os.path.dirname(abs_target)
        if not parent or os.path.isdir(parent):
            return True
        if dry:
            self._log.action(f"Would create directory {parent}")
            return True
        try:
            os.makedirs(parent)
        except OSError as e:
            self._log.warning(f"merge: failed to create directory {parent}: {e!s}")
            return False
        self._log.action(f"Creating directory {parent}")
        return True

    def _backup(self, abs_target: str, *, dry: bool) -> bool:
        ts = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{abs_target}.dotbot-backup.{ts}"
        if dry:
            self._log.action(f"Would back up {abs_target} to {backup_path}")
            return True
        try:
            os.rename(abs_target, backup_path)
        except OSError as e:
            self._log.warning(f"merge: failed to back up {abs_target} to {backup_path}: {e!s}")
            return False
        self._log.action(f"Backed up {abs_target} to {backup_path}")
        return True

    def _unlink(self, abs_target: str, *, dry: bool) -> bool:
        if dry:
            self._log.action(f"Would remove {abs_target}")
            return True
        try:
            if os.path.islink(abs_target) or os.path.isfile(abs_target):
                os.unlink(abs_target)
            else:
                self._log.warning(f"merge: refusing to remove non-file target {abs_target}")
                return False
        except OSError as e:
            self._log.warning(f"merge: failed to remove {abs_target}: {e!s}")
            return False
        self._log.action(f"Removing {abs_target}")
        return True

    def _write(self, abs_target: str, content: bytes, *, raw_target: str, dry: bool) -> bool:
        existed = os.path.lexists(abs_target)
        verb = "Would overwrite" if (dry and existed) else ("Would write" if dry else ("Overwriting" if existed else "Writing"))
        self._log.action(f"{verb} {raw_target} ({len(content)} bytes)")
        if dry:
            return True
        # Write to a temp sibling then rename for atomicity.
        tmp_path = f"{abs_target}.dotbot-merge.tmp"
        try:
            # Clean any stale tmp.
            if os.path.lexists(tmp_path):
                os.unlink(tmp_path)
            with open(tmp_path, "wb") as f:
                f.write(content)
            os.replace(tmp_path, abs_target)
        except OSError as e:
            self._log.warning(f"merge: failed writing {abs_target}: {e!s}")
            # Best-effort cleanup.
            try:
                if os.path.lexists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            return False
        return True

    def _enforce_mode(self, abs_target: str, mode: Any, *, dry: bool) -> bool:
        if mode is None:
            return True
        try:
            mode_int = int(str(mode), 8)
        except (TypeError, ValueError):
            self._log.warning(f"merge: invalid mode {mode!r}; expected octal string like '0444'")
            return False
        if dry:
            self._log.action(f"Would chmod {mode} {abs_target}")
            return True
        if not os.path.lexists(abs_target):
            # Nothing to chmod (can happen only in weird states).
            return True
        try:
            current = os.stat(abs_target).st_mode & 0o7777
            if current != mode_int:
                os.chmod(abs_target, mode_int)
                self._log.action(f"chmod {mode} {abs_target}")
        except OSError as e:
            self._log.warning(f"merge: failed to chmod {abs_target}: {e!s}")
            return False
        return True

    # ----------------------------------------------------------- conditionals

    def _test_success(self, command: str) -> bool:
        ret = shell_command(command, cwd=self._context.base_directory())
        if ret != 0:
            self._log.debug(f"Test '{command}' returned false")
        return ret == 0

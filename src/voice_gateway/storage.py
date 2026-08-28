"""Turn storage on local filesystem."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import UUID


class TurnStorage:
    def __init__(self, turns_dir: Path, retention_hours: int = 24) -> None:
        self._turns_dir = turns_dir
        self._retention_hours = retention_hours
        self._turns_dir.mkdir(parents=True, exist_ok=True)

    def turn_path(self, turn_id: str) -> Path:
        UUID(turn_id)
        return self._turns_dir / turn_id

    def clip_path(self, turn_id: str, clip_id: str) -> Path:
        if "/" in clip_id or ".." in clip_id:
            raise ValueError("invalid clip_id")
        return self.turn_path(turn_id) / f"{clip_id}.wav"

    def write_meta(self, turn_id: str, meta: dict[str, Any]) -> None:
        path = self.turn_path(turn_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def read_meta(self, turn_id: str) -> dict[str, Any] | None:
        meta_file = self.turn_path(turn_id) / "meta.json"
        if not meta_file.is_file():
            return None
        return json.loads(meta_file.read_text(encoding="utf-8"))

    def write_tenant_id(self, turn_id: str, tenant_id: str | None) -> None:
        """Records which tenant a turn's clips belong to (#50), called at turn
        start — before any clip is synthesized — so every clip a turn ever
        writes, including status audio from a turn that errors before
        completion, is covered by the same tenant tag.

        Single-tenant mode always calls this with `tenant_id=None` (the
        TenantRegistry never resolves one there), and a `None` tenant_id is a
        no-op: no file is written, so single-tenant turn directories are
        byte-identical to before this method existed.
        """
        if tenant_id is None:
            return
        path = self.turn_path(turn_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "tenant.json").write_text(json.dumps({"tenant_id": tenant_id}), encoding="utf-8")

    def read_tenant_id(self, turn_id: str) -> str | None:
        """The tenant recorded for this turn, or None if it was never tagged —
        either because it was written in single-tenant mode, or because it
        predates this field (a legacy clip). Callers in multi-tenant mode must
        treat None as "not this caller's" rather than "no restriction" (#50).
        """
        tenant_file = self.turn_path(turn_id) / "tenant.json"
        if not tenant_file.is_file():
            return None
        try:
            parsed = json.loads(tenant_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(parsed, dict):
            return None
        tenant_id = parsed.get("tenant_id")
        return tenant_id if isinstance(tenant_id, str) else None

    def cleanup_expired(self) -> int:
        cutoff = time.time() - self._retention_hours * 3600
        removed = 0
        for child in self._turns_dir.iterdir():
            if not child.is_dir():
                continue
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child)
                    removed += 1
            except OSError:
                continue
        return removed

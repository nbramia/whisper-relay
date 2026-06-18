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

import time
from uuid import uuid4

import pytest

from voice_gateway.storage import TurnStorage


def test_clip_path_rejects_traversal(tmp_path):
    storage = TurnStorage(tmp_path)
    turn_id = str(uuid4())
    with pytest.raises(ValueError):
        storage.clip_path(turn_id, "../etc/passwd")


def test_write_and_read_meta(tmp_path):
    storage = TurnStorage(tmp_path)
    turn_id = str(uuid4())
    storage.write_meta(turn_id, {"transcript": "hi"})
    assert storage.read_meta(turn_id)["transcript"] == "hi"


def test_cleanup_expired(tmp_path):
    storage = TurnStorage(tmp_path, retention_hours=0)
    turn_id = str(uuid4())
    path = storage.turn_path(turn_id)
    path.mkdir(parents=True)
    (path / "meta.json").write_text("{}", encoding="utf-8")
    past = time.time() - 7200
    import os

    os.utime(path, (past, past))
    assert storage.cleanup_expired() == 1
    assert not path.exists()

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


def test_write_and_read_tenant_id(tmp_path):
    storage = TurnStorage(tmp_path)
    turn_id = str(uuid4())
    storage.write_tenant_id(turn_id, "alice")
    assert storage.read_tenant_id(turn_id) == "alice"


def test_read_tenant_id_none_when_never_written(tmp_path):
    """Single-tenant mode, and any legacy turn predating this field (#50)."""
    storage = TurnStorage(tmp_path)
    turn_id = str(uuid4())
    assert storage.read_tenant_id(turn_id) is None


def test_write_tenant_id_none_is_a_no_op(tmp_path):
    """Single-tenant mode always calls this with tenant_id=None — no file
    should be created, so a single-tenant turn directory is unchanged (#50)."""
    storage = TurnStorage(tmp_path)
    turn_id = str(uuid4())
    storage.write_tenant_id(turn_id, None)
    assert not storage.turn_path(turn_id).exists()
    assert storage.read_tenant_id(turn_id) is None


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

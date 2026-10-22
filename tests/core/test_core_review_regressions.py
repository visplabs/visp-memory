"""Regressions found by the independent review of the 0.10.0 core changes."""

from __future__ import annotations

import sqlite3

import pytest

from visp_memory.core.lifecycle import MemoryLifecycleManager
from visp_memory.core.storage import LocalStorage


def test_reopening_a_store_validates_it_once_and_without_the_write_lock(
    tmp_path, monkeypatch
):
    # The check reads every memory and evidence row. Running it again under
    # BEGIN IMMEDIATE doubled every open and blocked every writer for the scan.
    LocalStorage(tmp_path).close()
    original = LocalStorage._validate_v5_schema.__func__
    writes_during_validation = []

    def validate(cls, conn):
        other = sqlite3.connect(tmp_path / "memories.db", timeout=0)
        try:
            other.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER)")
            other.commit()
            writes_during_validation.append(True)
        except sqlite3.OperationalError:
            writes_during_validation.append(False)
        finally:
            other.close()
        original(cls, conn)

    monkeypatch.setattr(LocalStorage, "_validate_v5_schema", classmethod(validate))

    LocalStorage(tmp_path).close()

    assert writes_during_validation == [True]


@pytest.mark.parametrize(
    "status", ["rejected", "pending", "merged", "quarantined", "superseded", "archived"]
)
def test_restore_returns_a_memory_to_the_status_it_was_deleted_from(tmp_path, status):
    storage = LocalStorage(tmp_path / "data")
    manager = MemoryLifecycleManager(storage, tmp_path / "lifecycle.db")
    memory_id = storage.store_memory("Reviewed proposal", repo_id="repo-a", auto_link=False)
    storage.update_memory(memory_id, status=status)

    assert manager.soft_delete(memory_id, actor_id="owner", reason="tidy")
    assert manager.restore(memory_id)

    assert storage.get_memory(memory_id)["status"] == status


def test_restore_without_a_recorded_status_makes_the_memory_active(tmp_path):
    storage = LocalStorage(tmp_path / "data")
    manager = MemoryLifecycleManager(storage, tmp_path / "lifecycle.db")
    memory_id = storage.store_memory("Old delete", repo_id="repo-a", auto_link=False)
    storage.update_memory(memory_id, status="deleted", metadata={"deletion": {}})

    assert manager.restore(memory_id)

    assert storage.get_memory(memory_id)["status"] == "active"

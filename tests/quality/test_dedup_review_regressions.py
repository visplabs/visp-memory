"""Regressions found by the independent review of the 0.10.0 dedup changes."""

from visp_memory.core.storage import LocalStorage
from visp_memory.quality.dedup import Deduplicator


def test_merge_keeps_the_survivors_own_relationship(tmp_path):
    # Re-adding an edge now updates it in place, so retargeting the duplicate's
    # inferred edge used to overwrite the survivor's confirmed one.
    storage = LocalStorage(tmp_path)
    kw = dict(repo_id="repo-a", auto_link=False)
    primary = storage.store_memory("Session cache is keyed by user id", **kw)
    duplicate = storage.store_memory("Session cache is keyed by the user id", **kw)
    service = storage.store_memory("Billing service reads the session cache", **kw)
    storage.add_relationship(
        service,
        primary,
        "depends_on",
        strength=1.0,
        evidence={"confidence": "manual", "reason": "Confirmed in review", "created_by": "alice"},
    )
    storage.add_relationship(
        service,
        duplicate,
        "depends_on",
        strength=0.2,
        evidence={"confidence": "inferred", "reason": "Guessed", "created_by": "auto"},
    )

    Deduplicator(storage).merge_memories([primary, duplicate])

    (edge,) = [
        edge
        for edge in storage.get_all_relationships("repo-a")
        if edge["source_id"] == service and edge["target_id"] == primary
    ]
    assert edge["strength"] == 1.0
    assert edge["evidence"]["created_by"] == "alice"


class _Collection:
    """Hands back identical embeddings for the given rows; storage stays real."""

    def __init__(self, ids):
        self.ids = ids

    def get(self, include=None):
        return {
            "ids": list(self.ids),
            "embeddings": [[1.0, 0.0] for _ in self.ids],
            "metadatas": [{} for _ in self.ids],
            "documents": ["" for _ in self.ids],
        }


def test_a_row_with_malformed_scope_metadata_does_not_fail_the_layer(tmp_path):
    storage = LocalStorage(tmp_path)
    kw = dict(layer="episodic", auto_link=False)
    first = storage.store_memory("Run make test before pushing", repo_id="repo-a", **kw)
    second = storage.store_memory("Run make test before pushing", repo_id="repo-a", **kw)
    malformed = storage.store_memory("Unrelated", repo_id="repo-b", **kw)
    storage.update_memory(malformed, metadata={"environment": ""})
    storage._get_collection = lambda layer: _Collection([first, second, malformed])

    report = Deduplicator(storage).find_duplicates(layer="episodic", threshold=0.9)

    assert report.determined
    assert [[item["id"] for item in group] for group in report.duplicates] == [
        [first, second]
    ]

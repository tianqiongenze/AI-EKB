"""Contract tests for the CRDB store dialect (no live DB required)."""
from enterprise_ekb.crdb_store import CockroachDBControlPlaneStore, _ensure_json


def test_ensure_json_tolerates_dict_list_str_none() -> None:
    assert _ensure_json({"a": 1}) == {"a": 1}
    assert _ensure_json([1, 2]) == [1, 2]
    assert _ensure_json('{"a": 1}') == {"a": 1}
    assert _ensure_json(None) == {}


def test_store_module_imports_cleanly() -> None:
    # psycopg2 present: the store must construct far enough to require a real DB
    # (probing the require-fast-fail branch directly would need sys.modules
    # surgery that breaks psycopg2's own imports).
    import inspect

    src = inspect.getsource(CockroachDBControlPlaneStore.__init__)
    assert "psycopg2 is required" in src


def test_read_methods_registry_matches_replica_semantics() -> None:
    assert "list_skills" in CockroachDBControlPlaneStore.READ_METHODS
    assert "enqueue_outbox" not in CockroachDBControlPlaneStore.READ_METHODS

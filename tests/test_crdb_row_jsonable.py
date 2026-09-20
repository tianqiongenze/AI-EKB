"""CRDB rows must be JSON-serializable end-to-end (audit 500 regression)."""
from datetime import datetime, timezone
from decimal import Decimal

from enterprise_ekb.crdb_store import _row_jsonable


def test_row_jsonable_converts_datetime_decimal() -> None:
    row = {
        "id": 7,
        "created_at": datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc),
        "accepted": 1,
        "amount": Decimal("1.25"),
    }
    out = _row_jsonable(row)
    import json

    json.dumps(out)  # must not raise
    assert isinstance(out["created_at"], str) and "2026-09-20" in out["created_at"]
    assert out["amount"] == 1.25

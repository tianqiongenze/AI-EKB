import hashlib
import hmac
import os
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from litestar.testing import TestClient

from enterprise_ekb.app import create_app
from enterprise_ekb.risk_control import (
    DistributedRateLimiter,
    NonceStore,
    verify_bearer_credential,
)

SIGNING_SECRET = "test-signing-secret"
BODY = b'{"tenant_id":"group","region_id":"cn-north-1","skill_name":"x","skill_version":"1.0.0","tool_name":"t","domain":"d","payload":{}}'


def signed_headers(method: str, path: str, nonce: str, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    signature = hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        "\n".join(
            [method.upper(), path, ts, nonce, hashlib.sha256(BODY).hexdigest()]
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-EKB-Timestamp": ts,
        "X-EKB-Nonce": nonce,
        "X-EKB-Signature": signature,
        "Content-Type": "application/json",
    }


def test_distributed_rate_limiter_memory_fallback_denies_burst() -> None:
    limiter = DistributedRateLimiter(limit_per_window=2, window_seconds=60, redis_client=None)
    assert limiter.allow("t1", limit=2) is True
    assert limiter.allow("t1", limit=2) is True
    assert limiter.allow("t1", limit=2) is False
    assert limiter.allow("other-key", limit=2) is True


def test_nonce_store_is_single_use() -> None:
    store = NonceStore(ttl_seconds=60)
    assert store.put_if_absent("n-1") is True
    assert store.put_if_absent("n-1") is False


def test_verify_bearer_credential_static_and_jwt() -> None:
    assert verify_bearer_credential("Bearer static-1", "static-1") is True
    assert verify_bearer_credential("Bearer wrong", "static-1") is False
    token = pyjwt.encode({"sub": "svc", "exp": int(time.time()) + 60}, "jwt-secret", algorithm="HS256")
    assert verify_bearer_credential(f"Bearer {token}", "static-1", "jwt-secret") is True
    expired = pyjwt.encode({"sub": "svc", "exp": int(time.time()) - 10}, "jwt-secret", algorithm="HS256")
    assert verify_bearer_credential(f"Bearer {expired}", "static-1", "jwt-secret") is False
    aud_token = pyjwt.encode(
        {"sub": "svc", "exp": int(time.time()) + 60, "aud": "ekb-control"},
        "jwt-secret",
        algorithm="HS256",
    )
    assert verify_bearer_credential(f"Bearer {aud_token}", "", "jwt-secret", "ekb-control") is True
    assert verify_bearer_credential(f"Bearer {aud_token}", "", "jwt-secret", "other-aud") is False


def test_admin_endpoint_accepts_valid_jwt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "static-token")
    monkeypatch.setenv("EKB_DATALAKE_ALLOWED_TOPIC_PREFIXES", "persistent://group/control/,persistent://group/connectors/")
    monkeypatch.setenv("EKB_DATALAKE_ALLOWED_TABLE_PREFIXES", "ekb_")
    monkeypatch.setenv("EKB_JWT_HS256_SECRET", "jwt-secret")
    monkeypatch.delenv("EKB_ENV", raising=False)
    client = TestClient(create_app(db_path=str(tmp_path / "jwt.db")))
    token = pyjwt.encode({"sub": "svc", "exp": int(time.time()) + 60}, "jwt-secret", algorithm="HS256")
    resp = client.post(
        "/datalake/tables/register",
        json={
            "table_name": "ekb_test_table",
            "table_format": "iceberg",
            "domain": "manufacturing",
            "source_topic": "persistent://group/connectors/erp-ingested",
            "tenant_id": "group",
            "region_id": "cn-north-1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_anti_replay_disabled_without_secret(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "rp-off.db")))
    resp = client.post("/mcp/invoke", content=BODY, headers={"Content-Type": "application/json"})
    assert resp.status_code != 401


def test_anti_replay_enforces_signature_and_nonce(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EKB_REQUEST_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.delenv("EKB_ENV", raising=False)
    client = TestClient(create_app(db_path=str(tmp_path / "rp-on.db")))
    path = "/mcp/invoke"

    missing = client.post(path, content=BODY, headers={"Content-Type": "application/json"})
    assert missing.status_code == 401
    assert missing.json()["detail"] == "signature_headers_missing"

    stale = client.post(
        path,
        content=BODY,
        headers=signed_headers("POST", path, "n-stale", timestamp=str(int(time.time()) - 9999)),
    )
    assert stale.status_code == 401
    assert stale.json()["detail"] == "timestamp_out_of_window"

    bad_sig = client.post(
        path, content=BODY, headers=signed_headers("POST", path, "n-bad") | {"X-EKB-Signature": "0" * 64}
    )
    assert bad_sig.status_code == 401
    assert bad_sig.json()["detail"] == "signature_invalid"

    fresh = str(int(time.time()))
    good_headers = signed_headers("POST", path, "n-good")
    first = client.post(path, content=BODY, headers=good_headers)
    assert first.status_code != 401

    replay = client.post(path, content=BODY, headers=signed_headers("POST", path, "n-good"))
    assert replay.status_code == 401
    assert replay.json()["detail"] == "replay_detected"

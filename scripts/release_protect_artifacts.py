from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "dist" / "protected"
BASELINE_PATH = OUTPUT_DIR / "manifest.verify.baseline.json"


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def protect_file(source: Path, key: str, obfuscation_level: int) -> dict[str, Any]:
    payload = source.read_bytes()
    key_bytes = key.encode("utf-8")
    transformed = payload

    for _ in range(max(1, obfuscation_level)):
        transformed = _xor_bytes(transformed, key_bytes)
        transformed = transformed[::-1]

    target = OUTPUT_DIR / source.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(transformed)

    return {
        "source": str(source.relative_to(ROOT)),
        "protected": str(target.relative_to(ROOT)),
        "sha256_source": _sha256(source),
        "sha256_protected": _sha256(target),
        "size": len(payload),
    }


def collect_targets() -> list[Path]:
    targets: list[Path] = []
    candidates = [
        ROOT / "src" / "enterprise_ekb",
        ROOT / "services" / "go-gateway",
        ROOT / "services" / "java-kgraph" / "src",
    ]
    for base in candidates:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in {".py", ".go", ".java", ".kt", ".yaml", ".yml"}:
                targets.append(path)
    return targets


def run(mode: str, key: str, obfuscation_level: int) -> int:
    if mode not in {"verify", "protect"}:
        raise ValueError("unsupported mode")
    if obfuscation_level < 1:
        raise ValueError("obfuscation_level must be >= 1")

    baseline_override = os.getenv("EKB_RELEASE_PROTECT_BASELINE_PATH", "").strip()
    baseline_path = Path(baseline_override) if baseline_override else BASELINE_PATH

    targets = collect_targets()
    targets.sort(key=lambda path: str(path.relative_to(ROOT)))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "mode": mode,
        "target_count": len(targets),
        "items": [],
    }

    if mode == "verify":
        for path in targets:
            manifest["items"].append(
                {
                    "source": str(path.relative_to(ROOT)),
                    "sha256": _sha256(path),
                    "size": path.stat().st_size,
                }
            )
        if baseline_path.exists():
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            if baseline != manifest:
                print(
                    f"[release-protect] verify mismatch against baseline: {_display_path(baseline_path)}",
                    file=sys.stderr,
                )
                return 2
    else:
        if not key or key == "yadea-ekb-default-key":
            raise ValueError("protect mode requires non-default EKB_RELEASE_PROTECT_KEY")
        for path in targets:
            manifest["items"].append(protect_file(path, key=key, obfuscation_level=obfuscation_level))

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if mode == "verify" and not baseline_path.exists():
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[release-protect] baseline created at {_display_path(baseline_path)}")
    print(f"[release-protect] mode={mode} targets={len(targets)} manifest={manifest_path.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Release-time code protection pipeline")
    parser.add_argument("--mode", choices=["verify", "protect"], default="verify")
    parser.add_argument("--key", default=os.getenv("EKB_RELEASE_PROTECT_KEY", "yadea-ekb-default-key"))
    parser.add_argument("--obfuscation-level", type=int, default=2)
    args = parser.parse_args()
    return run(mode=args.mode, key=args.key, obfuscation_level=args.obfuscation_level)


if __name__ == "__main__":
    raise SystemExit(main())

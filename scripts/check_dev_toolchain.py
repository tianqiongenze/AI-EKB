from __future__ import annotations

import shutil
import subprocess
import sys


def check_command(name: str) -> bool:
    return shutil.which(name) is not None


def check_grpcio_tools() -> bool:
    python_bin = shutil.which("python3.11") or shutil.which("python3") or sys.executable
    result = subprocess.run(
        [python_bin, "-c", "import grpc_tools.protoc"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def check_pyyaml() -> bool:
    python_bin = shutil.which("python3.11") or shutil.which("python3") or sys.executable
    result = subprocess.run(
        [python_bin, "-c", "import yaml"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main() -> int:
    checks: list[tuple[str, bool, str]] = [
        ("go", check_command("go"), "Install Go toolchain"),
        ("gopls", check_command("gopls"), "Install with: go install golang.org/x/tools/gopls@latest"),
        ("javac", check_command("javac"), "Install JDK 21+"),
        ("jdtls", check_command("jdtls"), "Install Eclipse JDT LS (e.g. brew install jdtls)"),
        ("mvn", check_command("mvn"), "Install Maven 3.9+"),
        (
            "yaml-language-server",
            check_command("yaml-language-server"),
            "Install with: npm install -g yaml-language-server",
        ),
        ("pyyaml", check_pyyaml(), "Install with: python3.11 -m pip install pyyaml"),
        ("grpcio-tools", check_grpcio_tools(), "Install with: python3.11 -m pip install grpcio-tools"),
    ]

    failed = [entry for entry in checks if not entry[1]]
    if failed:
        print("[dev-toolchain] FAILED")
        for name, _, hint in failed:
            print(f"- missing: {name} | {hint}")
        print("Run: scripts/bootstrap_dev_toolchain.sh")
        return 1

    print("[dev-toolchain] PASS")
    for name, _, _ in checks:
        print(f"- {name}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

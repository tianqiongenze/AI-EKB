# Contributing Guide

Thanks for contributing to the Enterprise AI Knowledge Base Platform (EKB).

## 1. Scope

This repository includes:

- Python control plane (`src/enterprise_ekb`)
- Java service skeleton (`services/java-kgraph`)
- Go gateway skeleton (`services/go-gateway`)
- Deployment assets (`infra/`)
- Architecture and governance documentation (`docs/`)

## 2. Development Setup

### Toolchain Bootstrap (Required for local Go/Java/proto development)

```bash
bash scripts/bootstrap_dev_toolchain.sh
python3 scripts/check_dev_toolchain.py
```

This installs/checks:

- `go`, `gopls`
- `javac`, `mvn`, `jdtls`
- Python `grpcio-tools`

### Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest -q
```

### Java

```bash
cd services/java-kgraph
mvn clean test
```

Java gRPC stubs are generated from `contracts/proto/ekb_contracts.proto` via Maven protobuf plugin during build.

### Go

```bash
cd services/go-gateway
go test ./...
```

## 3. Contribution Workflow

1. Open an issue (bug/feature/question)
2. Create a branch from `main`
3. Implement changes with tests/docs
4. Run quality checks locally
5. Submit PR using the PR template

## 4. Quality Gates

Before opening a PR, ensure:

- Python tests pass (`pytest -q`)
- Java tests pass (`mvn clean test`)
- Go tests pass (`go test ./...`) where available
- Updated docs for any architecture/API/deployment changes
- No secrets committed in code, docs, or configs
- No generated artifacts committed (see `.gitignore` and pre-commit hooks)

## 5. Documentation Requirements

If your change affects architecture or operations, update corresponding docs in:

- `docs/architecture/`
- `docs/global-deployment-and-dr.md`
- `docs/public-release-pack.md`
- `README.md`

## 6. Pre-commit Hooks (Required)

We use pre-commit to enforce repository hygiene and forbid generated artifacts.

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Hooks configuration is stored in `.pre-commit-config.yaml` and includes:

- whitespace and merge-conflict checks
- secret detection
- binary/artifact guards (e.g., `.DS_Store`, `*.pyc`, `target/`)
- Ruff linting

## 7. Security

Do not disclose vulnerabilities in public issues.

Please follow `SECURITY.md` for private vulnerability reporting.

## 8. Pull Request Expectations

PRs should include:

- Problem statement and rationale
- Scope and impacted modules
- Verification evidence (tests/build output)
- Risk and rollback notes for production-impacting changes

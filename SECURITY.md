# Security Policy

## Supported Versions

The following versions are currently supported with security updates:

| Version | Supported |
| --- | --- |
| `main` | ✅ |
| Older release branches | ⚠️ Best effort |

## Reporting a Vulnerability

Please **do not open a public issue** for security vulnerabilities.

Report vulnerabilities through private channels:

- Preferred: repository security advisory flow (GitHub private reporting)
- Fallback: maintainers' private security contact in your organization

When reporting, include:

1. Affected component(s) and version/commit
2. Reproduction steps or proof-of-concept
3. Impact assessment (confidentiality/integrity/availability)
4. Suggested remediation (if available)

## Disclosure Process

1. Maintainers acknowledge receipt within **3 business days**
2. Initial triage/severity assessment within **7 business days**
3. Fix plan and patch timeline communicated privately
4. Coordinated disclosure after patch/release

## Security Baseline Expectations

- No secrets in repository (passwords/tokens/certs)
- Sensitive deployment values injected via Kubernetes Secrets
- Dependency and image scanning in CI/CD
- Audit trails enabled for control-plane critical operations

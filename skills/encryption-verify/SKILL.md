---
name: encryption-verify
description: Run safe automated encryption verification checks for ts-prefect staging readiness. Use when asked to run encryption automated verification, staging encryption checks, Thomas testing automation, PLAINTEXT_FIELDS validation, or proxy-output-encryption readiness checks.
---

# Encryption Verify

Run non-destructive automated checks for the ts-prefect encryption rollout. The skill is intentionally safe by default: it does not deploy Prefect, mutate database rows, rotate keys, reset extensions, or run production checks.

## Quick Start

From a `ts-prefect` workspace:

```bash
python /Users/simon/dev/agent-workflows/skills/encryption-verify/scripts/run_encryption_verify.py
```

Use `--full-tests` only when the user explicitly wants the full pytest suite:

```bash
python /Users/simon/dev/agent-workflows/skills/encryption-verify/scripts/run_encryption_verify.py --full-tests
```

## What the Script Runs

Default required checks:

1. Verify expected encryption docs and scripts exist.
2. Run `uv run python scripts/check_plaintext_fields.py --verbose`.
3. Run focused local pytest coverage for encryption/classifier/schema/contract behavior.
4. Check docs do not contain stale signed-allow-list / `EncryptedStr` testing instructions.
5. Report target-state warnings for known pending migration work (`ciphertext_guard`, dual-mode fallback) without failing.

## Safety Rules

- Never run `prefect deploy`.
- Never run production Prefect flows.
- Never reset, delete, rotate, or overwrite key material.
- Never run dashboard bulk `Decrypt All` / `Encrypt All`.
- Treat network/proxy/DB staging checks as manual follow-ups unless the user explicitly provides environment and asks for them.

## Interpreting Results

- `PASS`: local automated checks passed.
- `WARN`: non-blocking current-state caveat or manual staging follow-up.
- `FAIL`: required local check failed; fix before asking Thomas to run manual staging testing.

Always summarize failures, warnings, and the exact command used.

## Terminal report

Load and apply `skills/references/terminal-outcomes.md`. Run its post-check for the files and ticket
artifacts touched by this run, then put one large banner and details block before individual check
results. This is local/readiness verification, not environment verification: use
`# ✅ STAGING VERIFIED` only if staging was actually exercised; otherwise use a truthful
`# ✅ READINESS CHECK PASSED` heading that does not claim deployment or final closure, set
`Closeout check: NOT READY`, and list the manual staging work under `Not verified`. Required-check
failure uses `# ❌ READINESS CHECK FAILED`.

---
name: verify
description: Verify features locally or in production. Modes — local (write DB, seed data, run tests) and prod (read-only, monitor state).
---

# Verify

Verify that a feature works correctly. Two modes based on environment.

## Modes

| Mode | What it does | Reference |
|---|---|---|
| `local` | Seeds test data, runs flows, verifies results with write DB access | `references/local.md` |
| `prod` | Read-only monitoring of production services and database state | `references/prod.md` |

## Usage

```
/verify local F002                    # Local verification of feature F002
/verify prod F001                     # Production verification of feature F001
/verify prod B0009                    # Verify bug fix in production
/verify prod "the new column is being populated"  # Freeform prod verification
/verify local F002 --skip-cleanup     # Keep test data for debugging
/verify prod F001 --lookback 24h      # Check last 24 hours
```

**Mode dispatch:** Read the corresponding reference file and follow that procedure.
Both modes spawn the `verifier` agent with environment-specific instructions.

---
name: auto-verify
description: Legacy alias for ticket-verify. Use ticket-verify staging|production for timer-friendly verification and automatic staging promotion.
max_turns: 200
---

# Auto-Verify (Legacy Alias)

`/auto-verify` is retained as a compatibility name for `/ticket-verify`.

Use:

```text
/ticket-verify staging [ticket...]
/ticket-verify production [ticket...]
```

The new verifier takes `staging` or `production` as the first argument. Staging PASS normally
calls `/ticket-promote` automatically. Production PASS marks the ticket `completed`.

For canonical behavior, load and follow:

```text
../ticket-verify/SKILL.md
```

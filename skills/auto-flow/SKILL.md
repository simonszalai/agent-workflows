---
name: auto-flow
description: Legacy alias for ticket-flow. Use ticket-flow for autonomous single-ticket execution; ticket-flow now deploys standalone tickets via auto-deploy but still does not perform behavior verification.
max_turns: 300
---

# Auto-Flow (Legacy Alias)

`/auto-flow` is retained as a compatibility name for `/ticket-flow`.

Do not follow the old auto-flow lifecycle. In particular:

- no `approved` ticket status;
- standalone deployment is only through the current `/ticket-flow` -> `/auto-deploy` path;
- no environment behavior verification;
- no epic orchestration;
- landing is governed by `../references/landing-policy.md`;
- statuses are governed by `../references/ticket-lifecycle.md`.

For new documentation and behavior, load and follow:

```text
../ticket-flow/SKILL.md
```

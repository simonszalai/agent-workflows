# Epic step body template

The `description` passed to `create_ticket` becomes the step's **source artifact**. A good step
body is self-sufficient: a builder should be able to implement it without re-reading the whole
epic. This structure is distilled from `ts/ts-prefect/F0111` (E0007-2) — read that ticket for a
full worked example.

Fill the sections that apply; omit ones that don't. Keep file references as `path:line` so they
stay clickable.

---

```markdown
# <Step title — the concrete deliverable>

> **Step `E000N-k` of epic E000N** (repo: `<repo>`, position k, milestone `<M# or "unassigned">`).
> Depends on: `<blocker ids or "none">`. Blocks: `<blocked ids>`.

**Scope (this step):** <one tight paragraph. State what is IN, bounded explicitly —
"ONLY the X case", "the short horizon only". Scope creep is the enemy; name the boundary.>

**Context:** <why this step exists and how it serves the epic. Point at the epic + the specific
consolidated-plan section / artifacts it implements.>

---
## Requirements

### R1 — <imperative title>
<Concrete requirement. Name the exact schema/table/field/endpoint/signature. Ground every claim
about the codebase in `path:line`. For each: say whether to REUSE existing code or build new,
and why.>

### R2 — <…>
…

---
## Cross-repo contract  *(only if this step exposes or consumes another repo's interface)*

- **Exposes** (if this step is a blocker for another repo): `<concrete surface — table.column,
  endpoint + payload, field, function signature, config key>`.
- **Consumes** (if this step depends on another repo): `<the surface it reads, and the blocker
  step that ships it: E000N-j / Fxxxx>`.

## What already exists (reuse — don't reinvent)
- **<thing>:** `path:line` — <what it already does>. ✅
- …

## Decisions (confirmed <date>, <who>)
1. <Locked decision>. ✅
2. …

## Open decisions to confirm
1. <Question the builder/user must resolve before/while implementing>.

## Out of scope (here)
- <Explicitly what belongs to OTHER steps or the epic — prevents this step from absorbing them.>

## Related
Epic **E000N** (step k). Depends on **<ids>**. See E000N artifacts #<n>.
```

---

## Field checklist for `create_ticket`

| Field | Rule |
|---|---|
| `repo` | The **one** repo this step lands in. |
| `type` | `feature` / `bug` / `refactor` — drives the id prefix (F/B/R). |
| `epic_id` | `E000N` — this is what makes the ticket a **step** (not a loose ticket). |
| `milestone_id` | Required when breaking work out under a named milestone; pass the label (`M3`), position (`3`), or UUID. |
| `depends_on` | Blocker step ids in the **same project**. Must match the epic DAG edges. |
| `related` | Include `E000N`. Add cross-project refs (`other-repo/F0004`) when relevant. |
| `tags` | `{"area": "<domain>", "related_epic": "E000N"}`. |
| `size` | `xs`/`s`/`m`/`l`/`xl`. If a step is `xl`, consider splitting it. |
| `summary_bullets` | 3–6 terse bullets (what / why / approach) — the dashboard ticket-header summary. Left unset it defaults to `[]` and the header is blank. |
| `status` | `backlog`. |
| `command` / `agent` | `"/epic-split"` / `"planner"` for actor tracking. |

After creation, set `position` and repeat/confirm `milestone_id` via `add_epic_step`, then set
the UUID edges via `set_epic_member_deps` — see the main SKILL.md, Phase 4.

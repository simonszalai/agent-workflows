---
name: migration-parity-check
description: Read-only report of staging↔main / staging↔prod schema-promotion truth. For ts-prefect after E0017, use Atlas/schema-truth evidence (not Alembic). For legacy migration repos, also checks Alembic/Prisma migration graph drift. Use before schema-bearing cross-branch promotion or when branches "look diverged".
max_turns: 80
---

# Migration / Schema Parity Check

Report the TRUTH before promoting schema-bearing work. This skill is read-only: it never
merges, migrates, or mutates anything.

## Current ts-prefect rule (post E0017, 2026-06-26)

ts-prefect has fully cut over from Alembic to Atlas:

- staging uses Atlas declarative `schema apply`;
- production uses `Run Atlas Reviewed Plan (Prod)` with a committed reviewed plan;
- active Alembic graph/config/scripts are decommissioned;
- production `public.alembic_version` is absent;
- schema truth is `cli_tools/verify_schema_truth.py` + Atlas no-op proof, not an Alembic
  version pointer.

Therefore, for ts-prefect **do not** run `uv run alembic heads`, query `alembic_version`, parse
`migrations/versions/**`, or advise `down_revision` repair. Historical Alembic memories explain
why Atlas was adopted; they are not current workflow instructions.

## What this catches

1. **Content divergence, not commit-count mythology.** PR squash/merge/re-author operations make
   `git log main..staging` counts misleading. Use content/patch equivalence.
2. **Environment object truth.** A version pointer (Alembic, Prisma metadata, Atlas plan file) is
   not enough; verify the actual tables/columns/functions/triggers/indexes the code expects.
3. **Legacy migration graph drift.** Only for repos that still have a migration graph: detect same
   revision id with different parents/content and report stranded environments.

## When to run

- Before any schema-bearing cross-branch promotion.
- When someone says "staging is N commits ahead of main" — verify it before acting.
- For ts-prefect: after an Atlas schema PR or before a production promotion that touches
  `ts_schemas/models/**`, `atlas.hcl`, `atlas/plans/**`, `cli_tools/atlas/**`, or
  `migrations/db_object_manifest.py`.
- For legacy Alembic repos: after any migration `down_revision` re-point, and before allowing the
  next migration-bearing promotion.

## Process

### 1. Git/content truth

Fetch the branches:

```bash
git fetch origin main staging --prune
```

Report all of:

```bash
git merge-base origin/main origin/staging
git cherry -v origin/main origin/staging
git cherry -v origin/staging origin/main
git diff --stat origin/main...origin/staging
```

Interpret patch-equivalent commits (`-`) as already applied content, not genuine divergence.

### 2. Detect schema lane

```bash
git diff --name-only origin/main...origin/staging -- \
  ts_schemas/models/ atlas.hcl atlas/plans/ cli_tools/atlas/ migrations/db_object_manifest.py \
  migrations/versions/ alembic/ prisma/migrations/ schema.prisma
```

Classify:

- **ts-prefect Atlas lane:** SQLModel/Atlas/DB-only manifest paths touched.
- **legacy Alembic lane:** `migrations/versions/**`, `alembic/**`, `migrations/env.py` exist/touched.
- **Prisma lane:** Prisma schema/migrations touched.
- **No schema lane:** promotion is code/config only.

### 3. Per-environment schema truth

For each relevant environment (staging, prod), verify actual schema objects.

**ts-prefect Atlas path:**

- Prefer existing workflow evidence first:
  - staging: latest successful `Run Atlas Schema Apply (Staging)` for the target commit;
  - prod: latest successful `Run Atlas Reviewed Plan (Prod)` for the target commit.
- The evidence must include:
  - Atlas dry-run/apply success or explicit no-op (`Schema is synced, no changes to be made`);
  - `cli_tools/atlas/check_schema_plan_safety.py` pass;
  - reviewed-plan exact match/no-op for prod;
  - DB-only hook pass;
  - `Schema truth OK: all model and DB-only objects present.`
- If direct DB readback is needed, query object families, not `alembic_version`: `vector`,
  enc-stats columns/functions/triggers, HNSW indexes, and any model objects named by the ticket.

**Legacy Alembic path:**

- Read the stamped revision if the repo still has `alembic_version`.
- Assert objects exist, not just the pointer. A non-zero schema-truth verifier with "version says
  head but objects missing" is a stranded-migration signature.

### 4. Cross-environment schema diff

Compare staging vs prod object inventories (tables/columns/functions/triggers/indexes) so a
promotion does not carry an assumption that only holds in one env. For ts-prefect, include the
DB-only manifest object families.

### 5. Migration graph drift (legacy repos only)

Skip this section for ts-prefect after E0017. It has no active Alembic graph.

For legacy Alembic repos:

```bash
uv run alembic heads          # must be exactly one
```

Then compare revision maps on `origin/main` and `origin/staging`:

- Parse every `migrations/versions/*.py` on both branches for `revision`, `down_revision`, and
  file content hash.
- For any revision id present on both branches, report **DRIFT** if either parent or content
  differs.
- Report main-only and staging-only revisions.

Use a concrete checker, not visual inspection. If the repo does not provide one, this portable
snippet is acceptable for legacy Alembic repos:

```bash
python - <<'PY'
import ast, hashlib, pathlib, subprocess, tarfile, tempfile

def revmap(treeish: str):
    td = tempfile.TemporaryDirectory()
    archive = pathlib.Path(td.name) / "m.tar"
    with archive.open("wb") as f:
        subprocess.run(["git", "archive", treeish, "migrations/versions"], check=True, stdout=f)
    tarfile.open(archive).extractall(td.name)
    out = {}
    for p in pathlib.Path(td.name, "migrations/versions").glob("*.py"):
        source = p.read_text()
        vals = {}
        for node in ast.parse(source).body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]; value = node.value
            elif isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]; value = node.value
            else:
                continue
            for name in names:
                if name in {"revision", "down_revision"}:
                    vals[name] = ast.literal_eval(value)
        normalized = "\n".join(
            line for line in source.splitlines()
            if "Revises:" not in line and not line.strip().startswith("#")
        )
        if "revision" in vals:
            out[vals["revision"]] = {
                "file": p.name,
                "down": vals.get("down_revision"),
                "hash": hashlib.sha256(normalized.encode()).hexdigest(),
            }
    return out

main, staging = revmap("origin/main"), revmap("origin/staging")
failed = False
for rev in sorted(set(main) & set(staging)):
    if main[rev]["down"] != staging[rev]["down"] or main[rev]["hash"] != staging[rev]["hash"]:
        failed = True
        print(f"DRIFT {rev}: main down={main[rev]['down']} file={main[rev]['file']} "
              f"vs staging down={staging[rev]['down']} file={staging[rev]['file']}")
print("main-only:", sorted(set(main) - set(staging)))
print("staging-only:", sorted(set(staging) - set(main)))
raise SystemExit(1 if failed else 0)
PY
```

Any duplicate-revision drift means migration debt exists. A migration-bearing selective
promotion should STOP unless the user explicitly approves an emergency exception and the same
run includes immediate reconciliation.

## Output

Load and apply `skills/references/terminal-outcomes.md`. After the read-only comparison, run the
shared post-check for any ticket/artifact updates made by the run and put one large banner plus
details block before the parity report. Because this is a read-only promotion precheck, never
claim deployment or final ticket closure: use `## ✅ PROMOTION PRECHECK PASSED` only when the
comparison is clean, or `## ❌ PROMOTION PRECHECK FAILED`/the blocked heading when reconciliation
or missing evidence prevents promotion, with the exact debt and next action underneath.

```text
Repo:      ts-prefect
Lane:      Atlas schema lane | legacy Alembic lane | Prisma lane | no schema lane
Content:   main ⊇ staging  (staging adds 0 genuine commits; 4 are consolidation noise)
           — OR — true divergence: staging +3 genuine, main +2 genuine
Env truth: staging  schema-truth=OK, Atlas apply/no-op=OK
           prod     schema-truth=OK, Atlas reviewed-plan/no-op=OK
Cross-env: staging vs prod schema delta: none
Graph:     ts-prefect Atlas — no Alembic graph (skip)
           — OR — legacy Alembic heads=1, revision drift=none
Verdict:   SAFE to promote | SCHEMA-LANE — use Atlas/reviewed plan | STRANDED env — reconcile first | DIVERGED — full parity merge

Recommended action:
- <one of: proceed / use ts-prefect Atlas reviewed-plan promotion / reconcile staging then retry /
  full staging→main parity merge / legacy schema-first migration lane>
```

## Notes

- This is the tool to reach for instead of trusting `git log` counts.
- For ts-prefect, the safe high-velocity model is parallel code work plus Atlas additive-only
  schema changes with reviewed prod plans. Do not resurrect Alembic.
- For legacy Alembic repos, parallel code work plus serialized schema work remains the safe model:
  land backward-compatible schema first on current `main`, deploy it, then immediately sync
  `main` to `staging` before branches depend on the new objects.

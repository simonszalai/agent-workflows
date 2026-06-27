---
name: migration-parity-check
description: Report the TRUTH about staging↔main divergence before promoting — content/patch-equivalence (not commit counts) plus per-environment migration-version-vs-actual-schema-objects. Use before any cross-branch promotion that involves migrations, or when branches "look diverged". Read-only.
max_turns: 80
---

# Migration Parity Check

Read-only diagnosis that answers the two questions commit-count comparisons get wrong, and that
caused the 2026-06-16 ts-prefect fork (see R0031/R0032):

1. **Is staging actually diverged from main, or does it just look that way?** Promotions
   consolidate/re-author commits, so `git log main..staging` counts are misleading — a branch
   can show "26 commits ahead" while its *content* is already a subset of the other.
2. **Does each environment's database actually have the objects its `alembic_version` claims?**
   A re-linearized migration graph leaves `alembic upgrade head` a silent no-op on an env that
   already passed the moved node — the version pointer lies while tables/columns/triggers are
   missing.
3. **Do the long-lived branches contain the same Alembic revision id with different parents or
   content?** That duplicate-revision drift is the warning sign that selective migration
   cherry-picks have created reconciliation debt.

This skill only reports. It never merges, migrates, or mutates anything.

## Usage

```text
/migration-parity-check                 # staging vs main, both envs
/migration-parity-check --env staging   # limit env-truth check to one env
```

## When to use

- Before `/promote-to-production`, `/ticket-promote`, or `/promote-ready-to-prod` when the
  ticket touches `migrations/`.
- Whenever someone says "staging is N commits ahead of main" — verify it before acting.
- After any migration `down_revision` re-point, to confirm no env was stranded.
- After any migration-bearing selective promotion, before allowing the next migration-bearing
  promotion. Duplicate-revision drift must be reconciled immediately, not carried as backlog.

## Process

### 1. Content divergence (not commit counts)

```bash
git fetch origin main staging --prune
MB=$(git merge-base origin/main origin/staging)
# A real merge of each direction; an empty tree-diff means "already contained".
git merge-tree --write-tree origin/main origin/staging >/dev/null 2>&1
```

Classify using **patch/tree equivalence**, never `--oneline | wc -l`:

- `git diff --stat origin/main origin/staging` empty → **identical**.
- merge of staging into main yields a tree identical to main → **main ⊇ staging** (staging has
  nothing new; "ahead by N" is consolidation noise).
- and symmetrically for **staging ⊇ main**.
- both directions add content → **true divergence**.

Use `git cherry -v origin/main origin/staging` to separate genuinely-missing commits (`+`) from
already-applied-by-patch (`-`), and report the genuine set only.

### 2. Per-environment schema truth

For each environment (staging, prod), confirm the DB's claimed head matches reality:

1. Read the stamped revision — via the postgres MCP (`postgres_staging` / `postgres_prod`):
   `select version_num from alembic_version;`
2. Assert the **objects** exist, not just the pointer. In ts-prefect run the schema-truth
   verifier against that env's `DATABASE_URL` (read-only without `--reconcile`):

   ```bash
   DATABASE_URL=<env-url> uv run python cli_tools/verify_schema_truth.py
   ```

   A non-zero exit with "version says head but objects missing" is the **stranded-migration
   signature** — the env needs the missing migration's idempotent DDL re-applied
   (`verify_schema_truth.py --reconcile` for DB-only objects; a real migration run for model
   tables). Do NOT promote on top of a stranded env.

### 3. Cross-environment schema diff

Compare staging vs prod object inventories (tables/columns/functions/triggers) so a promotion
doesn't carry an assumption that only holds on one env. Surface any delta.

### 4. Migration-graph sanity and duplicate-revision drift

```bash
uv run alembic heads          # must be exactly one
```

Confirm no migration file's `down_revision` was re-pointed relative to the target branch (the
re-linearization hazard) — `cli_tools/lint_migrations.py` enforces this in CI; flag it here too.

Also compare the Alembic revision maps on `origin/main` and `origin/staging`:

- Parse every `migrations/versions/*.py` on both branches for `revision`, `down_revision`, and
  file content hash.
- For any revision id present on both branches, report it as **DRIFT** if either:
  - `down_revision` differs, or
  - the file content differs after normalizing only comments/docstring `Revises:` lines.
- For revision ids present on only one branch, report them as `main-only` or `staging-only` and
  classify whether they are expected based on the content-divergence result.

Use a concrete checker, not visual inspection. If the repo does not provide one, this portable
snippet is acceptable:

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
run includes an immediate reconciliation plan.

## Output

```text
Migration parity check
Content:   main ⊇ staging  (staging adds 0 genuine commits; 4 are consolidation noise)
           — OR — true divergence: staging +3 genuine, main +2 genuine
Env truth: staging  alembic=f104  objects=OK
           prod     alembic=f104  objects=OK
Cross-env: staging vs prod schema delta: none
Heads:     1 (f104_relevance_band_type)
Revision drift: none
           — OR — DRIFT f109_x: main parent=f108_b, staging parent=f107_a
Verdict:   SAFE to promote  |  STRANDED env — reconcile first  |  DIVERGED — full parity merge

Recommended action:
- <one of: proceed with ticket promotion / reconcile staging then retry /
  full staging→main parity merge (real --merge commit) / schema-first migration lane>
```

## Notes

- This is the tool to reach for instead of trusting `git log` counts. A migration-bearing
  ticket is **not** eligible for selective cherry-pick off a diverged branch — see the
  ts-prefect CLAUDE.md "Migrations Must Be Order-Independent + Cross-Branch Discipline" rule.
- The safe high-velocity model is parallel code work plus serialized schema work: land
  backward-compatible schema changes first on current `main`, deploy them, then immediately sync
  `main` to `staging` before branches depend on the new objects.
- Background: R0031 (research), R0032 (the schema-truth gate + lint this skill pairs with).

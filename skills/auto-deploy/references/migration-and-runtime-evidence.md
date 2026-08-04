# Migration and runtime-evidence routing

Load this reference only when the bounded P6 inventory contains schema/migration paths or when the
deployment guide expects durable rows/logs from a runtime producer.

## Migration detection and execution

The repository active migration system is authoritative. Detect ts-prefect Atlas paths
(`ts_schemas/models/`, `atlas.hcl`, `atlas/plans/`, `cli_tools/atlas/`,
`migrations/db_object_manifest.py`), legacy migration directories (`alembic/`,
`migrations/versions/`), and Prisma schema/migration paths. Review the project deploy contract for
the exact environment-specific command. A schema change without its required reviewed plan or
migration artifact is a STOP before merge.

When no project-specific deploy command exists, rely on the documented CI auto-migration only when
the repository explicitly guarantees it for the target branch. Otherwise stop and report the
missing migration owner. A migration preflight never replaces the real migration or its
postcondition verification.

## Runtime evidence producer gate

Also compare the deployment guide / milestone gate evidence contract against the detected diff.
If any verification row expects runtime behavior from a Prefect flow, scheduler, worker,
supervisor-managed deployment, webhook, canary, stored-row observer, or live deployment, prove
that one of these is true before merging:

- the diff adds/changes the producing flow entrypoint plus the relevant deployment config
  (`prefect.*.yaml`, supervisor registration, worker/schedule config, etc.);
- the deployment guide names an existing deployed object that will produce the evidence, and
  `prefect deployment ls` / the authoritative deploy system confirms it exists in the target
  environment; or
- the deployment guide names an explicit deploy-owned canary/CLI command that will be run in
  Phase 8 and leave durable evidence for `/ticket-verify`.

If the evidence contract expects runtime rows/logs but the diff is only schema/parser/model code
and no existing deploy object/command can produce the rows, STOP as a scope mismatch. Do not
silently skip Prefect deploy merely because `prefect.staging.yaml` / `prefect.prod.yaml` is
unchanged; report that planning/splitting missed the runtime surface required by the gate.


# Deployment and Configuration Ownership

Resolve deployment/configuration ownership before build work. Missing configuration is not evidence
that a token or secret should exist: every needed value or action must be classified explicitly as
`non_secret_config`, `secret_value`, or `manual_gate`.

## Inventory contract

Planning owns one cached inventory of every tracked deploy manifest, environment/config file, and
secret-name manifest implicated by the epic. For each asset record:

- tracked path, owner/source repo, destination repo/environment, and resolved workspace path;
- every required key/action with its classification, source/owner, destination, application route,
  safe-state handling, and verification evidence;
- the step ticket and dependency edge when the owner is a third repo.

Never hide third-repo config work inside another repo's code ticket. Create an explicit step ticket
in the owner repo and place it in the DAG. A missing owner workspace is an early readiness gap, not
permission to edit a different checkout or invent a secret.

Write the inventory as bounded JSON in the workflow scratch packet and validate it with:

```bash
bin/deployment-ownership-contract <inventory.json>
```

The guide may say `FINALIZED` only when every required row contains all six fields above. A
`straight_to_prod` preflight runs non-mutatingly before the first build and blocks on any ownership,
workspace, dependency, or guide gap. A `staging_only` run records the same issues as
`status="record_only"` so an unrelated staging build is not falsely blocked. Promotion creates a
fresh `mode="promotion"` inventory with `recheck_of` and `rechecked_at_epoch`; it never relies on
the earlier snapshot.

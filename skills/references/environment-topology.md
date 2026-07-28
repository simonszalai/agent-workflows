# Environment Topology

`config/environment-topology.json` is the canonical capability registry. Resolve it with
`bin/environment-capability`; do not infer an environment mode because staging is unreachable.

The identity key is `(project, repo, surface)`. Each entry records the audience,
`staging_available`, `verification_environment`, and the approved production verifier mode.
AutoDev's `autodev-dashboard/dashboard` surface is internal single-user, has no staging
environment, and is production-verified through `read_only_backdoor_browser`.

Production-only routing is selected only when all four mechanical gates pass:

1. an exact registry entry says `staging_available: false` and
   `verification_environment: production`;
2. the acceptance contract explicitly requires production verification;
3. the user explicitly authorized production browser verification; and
4. the requested verifier mode exactly matches the registered approved mode.

Missing, unknown, malformed, or partly authorized topology fails closed to `staging_first`.
Staging being unavailable never upgrades an unknown project to production-only.

For visible-surface verification, `production_visible_surface_allowed` remains false until the
caller also attests the mechanically named preflights: short expiry enforced, mutation denied,
project scoped, secret-safe transport, real browser available, and all other producers preflighted.

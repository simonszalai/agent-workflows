/ticket-verify --scheduled

This is the unattended nightly run. Verify the full default queue for staging and production
(read-only in both). On a clean staging PASS, promote by merging to main only — do NOT run
production deploy steps; stop and report "promotion-ready, prod deploy awaiting Simon".
Post the one-line summary to #autodev-nightly with all detail in the thread.

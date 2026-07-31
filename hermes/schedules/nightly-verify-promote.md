/ticket-verify --scheduled

This is the unattended nightly run. Verify the full default queue for staging and production
(read-only in both). VERIFY-ONLY: never merge or promote — merging to main is a de-facto
production deploy for ts-prefect (flows git_clone main at runtime). On a clean staging PASS,
stop and report "promotion-ready — prod promotion awaiting Simon".
Post the one-line summary to #autodev-nightly with all detail in the thread.

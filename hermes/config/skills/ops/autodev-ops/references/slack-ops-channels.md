# Slack ops channels (TS Invest)

Bot user: `hermes`. Token: `SLACK_BOT_TOKEN` in `~/.hermes/.env`.

| Channel | ID | Role |
|---------|-----|------|
| product-intake | `C0BKB94L61Y` | Hermes home / free-response (often only allowlisted channel in env) |
| ops-alerts | `C0BHTPTD087` | Provider/quota recoveries and outages (e.g. NodeMaven, xAI) |
| autodev-incidents | `C0BM7CUHGAV` | FAIL routing from scheduled runs; @ human |
| autodev-health | `C0BM25N3DPX` | health-6h one-liners + ticket ids |
| autodev-nightly | `C0BMZQWBDPA` | nightly-dream / nightly-verify-promote |
| record-investigations | `C0BKH1CCWNS` | Research / investigation threads |
| issue-updates | `C09TCATH42X` | Issue updates (bot may not be member) |
| all-ts-invest | `C09T31TQLCV` | Org-wide (bot often not member) |

## Access checks
```bash
# auth
curl -s -X POST https://slack.com/api/auth.test -H "Authorization: Bearer $SLACK_BOT_TOKEN"
# history (fails with not_in_channel if not invited)
# conversations.history channel=<ID> limit=10
```

## Notes
- `SLACK_ALLOWED_CHANNELS` / `SLACK_FREE_RESPONSE_CHANNELS` may list only home; API can still read other channels **if** the bot is a member.
- `search.messages` with bot token frequently returns `not_allowed_token_type` — prefer channel history.
- Invite `@hermes` to any ops channel before expecting history.

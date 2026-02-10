# Claude Shared Config

User-level Claude Code agents, skills, and commands — version-controlled and synced to project repos for cloud compatibility.

## How it works

```
┌─────────────────────────────────┐
│  This repo (claude-shared-config)│
│  agents/  skills/  commands/     │
└──────────┬──────────────────────┘
           │
     setup.sh (once)
           │
           ▼
┌──────────────────────────────────┐
│  ~/.claude/                       │
│  agents → symlink to this repo    │
│  skills → symlink to this repo    │
│  commands → symlink to this repo  │
│  settings.json (untouched)        │
│  logs/ (untouched)                │
└──────────────────────────────────┘
           │
     post-commit hook (per project repo)
           │
           ▼
┌──────────────────────────────────┐
│  any-project/.claude/             │
│  agents/   ← synced copies       │
│  skills/   ← synced copies       │
│  commands/ ← synced copies       │
│  settings.json (project's own)    │
└──────────────────────────────────┘
```

**Locally:** You work at user level via symlinks. Claude Code sees everything.

**In cloud (Claude Code Web):** The project repo carries synced copies in `.claude/`, so the sandbox has access too.

**Collision handling:** Project-level items always win. If a project already has `.claude/agents/code-reviewer.md`, the sync skips it. Synced items are tracked with `.synced-from-user` markers so the hook knows what it owns.

## Setup

### 1. Clone and symlink (once per machine)

```bash
git clone git@github.com:youruser/claude-shared-config.git ~/claude-shared-config
cd ~/claude-shared-config
bash setup.sh
```

### 2. Install the hook (once per project repo)

```bash
cd /path/to/your-project
bash ~/claude-shared-config/install-hook.sh
```

Now every commit in that project will sync your user-level config into `.claude/`.

### 3. Add your agents, skills, commands

Put them in this repo as usual:

```
agents/my-agent.md
skills/my-skill/SKILL.md
commands/my-command.md
```

They're immediately available locally (via symlinks) and will sync to project repos on next commit.

## Updating agents from cloud

If Claude edits a synced agent in a cloud session (changes land on a branch), pull the branch and run:

```bash
# From the project repo, after pulling cloud changes
cp .claude/agents/my-agent.md ~/claude-shared-config/agents/
cd ~/claude-shared-config && git add -A && git commit -m "Update from cloud"
```

## .gitignore for project repos

Add to each project's `.gitignore` if you want to hide the sync markers:

```
.claude/**/.synced-from-user
.claude/**/.synced-from-user.*
```

Or commit them — they're harmless and help the hook track ownership.
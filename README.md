# Agent Workflows

Shared Claude Code agents, skills, and commands for all projects.

## Contents

- **Agents** - Specialized agent roles (reviewer-code, planner, researcher, etc.)
- **Commands** - Workflow orchestration (/build, /review, /plan, /lfg, etc.)
- **Skills** - Methodology and knowledge (review patterns, research methods, etc.)

## Distribution

| Environment     | Mechanism                              | Direction |
| --------------- | -------------------------------------- | --------- |
| Local dev       | `~/.claude/` symlinks to this checkout | Two-way   |
| Claude Code web | SessionStart hook clones + copies      | One-way   |
| NanoClaw        | Volume mount into container            | Two-way   |

### Local setup (once per machine)

```bash
git clone git@github.com:simonszalai/agent-workflows.git ~/dev/agent-workflows
ln -s ~/dev/agent-workflows/agents ~/.claude/agents
ln -s ~/dev/agent-workflows/commands ~/.claude/commands
ln -s ~/dev/agent-workflows/skills ~/.claude/skills
```

### Cloud setup (automatic)

Each project's `deploy/cloud-setup.sh` handles cloning this repo and copying files into
`~/.claude/` when `$CLAUDE_CODE_REMOTE=true`. The Claude GitHub app must be installed on
this repo for the clone to work.

### NanoClaw setup

Mount this repo's directories into the container at `~/.claude/`:

```yaml
volumes:
  - source: /path/to/agent-workflows/agents
    target: /home/user/.claude/agents
  - source: /path/to/agent-workflows/commands
    target: /home/user/.claude/commands
  - source: /path/to/agent-workflows/skills
    target: /home/user/.claude/skills
```

## Resolution precedence

Claude Code checks project `.claude/` first, then user `~/.claude/`. Project-specific
agents/skills/commands override shared ones of the same name.

## Adding items

Put new agents, skills, and commands directly in this repo. They become available
immediately in all projects (locally via symlinks, cloud on next session start).

## Project-specific items

Items that only make sense for one project stay in that project's `.claude/`:

- Project-specific agents (e.g., `investigator-prefect.md` in ts-prefect)
- Project-specific commands (e.g., `/deploy` in ts-prefect)
- Project-specific skills (e.g., `tool-prefect` in ts-prefect)

## Two-way updates

Locally, symlinks mean edits to `~/.claude/skills/` directly modify this repo. When
`/compound` updates a shared skill, the change propagates to agent-workflows automatically.

In cloud sessions, file changes are ephemeral. Learnings persist via the memory service
(autodev-memory) instead.

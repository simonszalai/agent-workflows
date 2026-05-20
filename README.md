# Agent Workflows

Shared agent workflows, skills, hooks, and tool-specific agent definitions for all projects.

## Contents

- **Skills** - Shared methodology and knowledge (review patterns, research methods, etc.)
- **Agents** - Tool-specific specialized agent roles (reviewer, planner, researcher, etc.)
- **Hooks** - Shared shell hooks for autodev-memory context injection
- **Commands** - Legacy Claude command wrappers kept only where still needed

## Distribution

| Environment     | Mechanism                                      | Direction |
| --------------- | ---------------------------------------------- | --------- |
| Local dev       | `~/.claude/`, `~/.agents`, `~/.codex` symlinks | Two-way   |
| Cloud sessions  | SessionStart hook clones + copies              | One-way   |
| NanoClaw        | Volume mount into container                    | Two-way   |

### Local setup (once per machine)

```bash
git clone git@github.com:simonszalai/agent-workflows.git ~/dev/agent-workflows
ln -s ~/dev/agent-workflows/agents ~/.claude/agents
ln -s ~/dev/agent-workflows/commands ~/.claude/commands
ln -s ~/dev/agent-workflows/skills ~/.claude/skills
ln -s ~/dev/agent-workflows/skills ~/.agents/skills
ln -s ~/dev/agent-workflows/hooks ~/.claude/hooks
ln -s ~/dev/agent-workflows/hooks ~/.codex/hooks
```

### Cloud setup (automatic)

Each project's `deploy/cloud-setup.sh` handles cloning this repo and copying files into
the tool-specific config directory when running in a remote environment. The GitHub app for
that environment must be installed on this repo for the clone to work.

### NanoClaw setup

Mount this repo's directories into the container at the tool-specific config locations:

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

Codex reads shared skills from `.agents/skills` and tool-specific agents from `.codex/agents`.
Keep skills shared, but keep agent definitions in the format each tool expects.

## Adding items

Put new shared skills and hooks directly in this repo. They become available immediately in
all projects locally via symlinks, and in cloud sessions on next session start. Keep new
agents tool-specific unless/until a generator owns the conversion.

## Project-specific items

Items that only make sense for one project stay in that project's config directories:

- Project-specific agents (e.g., `investigator-prefect.md` in ts-prefect)
- Project-specific skills (e.g., `tool-prefect` in ts-prefect)
- Legacy Claude command wrappers, only when a slash command still needs to exist

## Hooks

Memory system hooks live in `hooks/` and are symlinked to `~/.claude/hooks/` and
`~/.codex/hooks/`.

### Required: `~/.config/autodev-memory/.env`

Hooks need API credentials to reach the autodev-memory service. These **must** be
in a dedicated `.env` file — not just in `~/.zshrc` — because hooks run as bash
subprocesses that do not inherit zsh shell exports (especially when launched from
GUI apps like Conductor).

```bash
# Create once per machine:
mkdir -p ~/.config/autodev-memory
cat > ~/.config/autodev-memory/.env << 'EOF'
AUTODEV_MEMORY_API_TOKEN=<your-token>
AUTODEV_MEMORY_API_URL=https://autodev-memory.onrender.com
EOF
```

`mem-lib.sh` sources this file on every hook invocation (line 83-85). Without it,
hooks fail silently on resume/compact triggers with "AUTODEV_MEMORY_API_TOKEN not set".

### Hook files

| File | Event | Purpose |
|---|---|---|
| `autodev-memory-session-start.sh` | SessionStart | Injects starred entries + knowledge menu |
| `autodev-memory-pre-agent.sh` | PreToolUse (Agent) | Briefs sub-agents with memory context |
| `mem-lib.sh` | (shared library) | Logging, env parsing, HTTP, entry loading |
| `mem-err-trap.sh` | (shared library) | Error trapping for clean hook output |


## Two-way updates

Locally, symlinks mean edits to `~/.claude/skills/` or `~/.agents/skills/` directly modify
this repo. When the `compound` skill updates a shared skill, the change propagates to
agent-workflows automatically.

In cloud sessions, file changes are ephemeral. Learnings persist via the memory service
(autodev-memory) instead.

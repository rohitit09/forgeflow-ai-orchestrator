#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Runtime directories ───────────────────────────────────────────────────────

for dir in bugs workspace repo-context reviews plans; do
  mkdir -p "$ROOT/$dir"
  echo "Created $dir/"
done

# ── .env (only created if missing) ───────────────────────────────────────────

if [ ! -f "$ROOT/.env" ]; then
  if [ -f "$ROOT/.env.example" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "Created .env from .env.example — fill in your credentials"
  else
    touch "$ROOT/.env"
    echo "Created empty .env — no .env.example found"
  fi
else
  echo "Skipped .env (already exists)"
fi

# ── Symlinks ──────────────────────────────────────────────────────────────────

# AGENTS.md is OpenCode's equivalent of CLAUDE.md — symlink so they stay in sync
ln -sf CLAUDE.md "$ROOT/AGENTS.md"

mkdir -p "$ROOT/.claude/commands"
mkdir -p "$ROOT/.opencode/commands"

for cmd in "$ROOT"/commands/*.md; do
  name="$(basename "$cmd")"
  ln -sf "../../commands/$name" "$ROOT/.claude/commands/$name"
  ln -sf "../../commands/$name" "$ROOT/.opencode/commands/$name"
done

# Custom agents live at agents/. Symlink them under .claude/agents/ so Claude Code
# discovers them as subagent_types (execute-plan's orchestrator dispatch relies on
# this). OpenCode picks up agents/ directly via opencode.jsonc — no symlink needed.
mkdir -p "$ROOT/.claude/agents"

for ag in "$ROOT"/agents/*.md; do
  name="$(basename "$ag")"
  ln -sf "../../agents/$name" "$ROOT/.claude/agents/$name"
done

echo "Symlinks created:"
echo "  .claude/commands/   → commands/"
echo "  .opencode/commands/ → commands/"
echo "  .claude/agents/     → agents/"

# ── Config JSON files (only created if missing) ───────────────────────────────

mkdir -p "$ROOT/config"

if [ ! -f "$ROOT/config/repositories.json" ]; then
  cat > "$ROOT/config/repositories.json" << 'EOF'
{
  "repositories": [
    {
      "id": "my_backend",
      "name": "My Backend",
      "type": "backend",
      "path": "workspace/my_backend",
      "git_url": "git@github.com:org/my_backend.git",
      "base_branch": "staging",
      "feature_merge_dest_branch": "dev",
      "bug_merge_dest_branch": "staging",
      "protected_branches": ["master", "staging", "production"],
      "dependent_repos": [],
      "dependency_evidence": {},
      "_rejected_dependencies": {},
      "runtime": {
        "role": "backend",
        "language": "Python",
        "runtime_version": "python 3.11",
        "framework": "Django 4.2 + Django REST Framework 3.14",
        "test": false,
        "test_cmd": ". venv/bin/activate && python manage.py test",
        "lint_command": null,
        "format_command": null,
        "venv": "workspace/my_backend/venv",
        "setup": null,
        "copy_files": [
          { "from": "workspace/my_backend/.env", "to": ".env" },
          { "from": "workspace/my_backend/app/settings_local.py", "to": "app/settings_local.py" }
        ],
        "external_services": ["mysql", "redis", "aws_s3"],
        "analyzed_at": null
      }
    },
    {
      "id": "my_frontend",
      "name": "My Frontend",
      "type": "frontend",
      "path": "workspace/my_frontend",
      "git_url": "git@github.com:org/my_frontend.git",
      "base_branch": "staging",
      "feature_merge_dest_branch": "dev",
      "bug_merge_dest_branch": "staging",
      "protected_branches": ["master", "staging"],
      "dependent_repos": ["my_backend"],
      "dependency_evidence": {
        "my_backend": "src/services/axios.js — axiosInstance baseURL reads REACT_APP_API_URL; used by all REST API calls"
      },
      "_rejected_dependencies": {},
      "runtime": {
        "role": "frontend",
        "language": "JavaScript",
        "runtime_version": "node 18",
        "framework": "React 18 (Create React App)",
        "test": false,
        "test_cmd": null,
        "lint_command": null,
        "format_command": null,
        "venv": "workspace/my_frontend/node_modules",
        "setup": null,
        "copy_files": [
          { "from": "workspace/my_frontend/.env.development", "to": ".env.development" },
          { "from": "workspace/my_frontend/.env.staging", "to": ".env.staging" }
        ],
        "external_services": [],
        "analyzed_at": null
      }
    }
  ],
  "branch_naming": {
    "_note": "Templates use {jira_key}, {plan_id}, {bug_id}, {description} placeholders. Description is a 2-5 word kebab-case slug of the plan or bug title. plan_id already carries a date-prefixed slug so no {description} is needed in the no-jira fallback.",
    "feature_with_jira": "feature-{jira_key}-{description}",
    "feature_no_jira":   "feature-{plan_id}",
    "bug_with_jira":     "bug-{jira_key}-{description}",
    "bug_no_jira":       "bug-{bug_id}-{description}"
  },
  "commit_message": {
    "_note": "Templates use {type} (feat|fix|refactor|test|chore), {scope} (repo or module), {summary} (one-line result), {jira_key}, {task_id}, {bug_id}. plan_task_* keeps {task_id} in the subject so /resume-plan can grep git log for it. bug_fix_* has no task_id — the /fix-bug flow does one commit per repo, no reconciliation.",
    "plan_task_with_jira": "{type}({scope}): {summary} {jira_key} ({task_id})",
    "plan_task_no_jira":   "{type}({scope}): {summary} ({task_id})",
    "bug_fix_with_jira":   "{type}({scope}): {summary} {jira_key}",
    "bug_fix_no_jira":     "{type}({scope}): {summary}"
  }
}
EOF
  echo "Created config/repositories.json (edit to add your repos)"
else
  echo "Skipped config/repositories.json (already exists)"
fi

if [ ! -f "$ROOT/config/integrations.json" ]; then
  cat > "$ROOT/config/integrations.json" << 'EOF'
{
  "sentry": {
    "base_url": "${SENTRY_BASE_URL}",
    "auth_token": "${SENTRY_AUTH_TOKEN}",
    "organization": "${SENTRY_ORG}",
    "sync_bug_source": true,
    "sync_days": 2,
    "projects": {}
  },
  "jira": {
    "base_url": "${JIRA_BASE_URL}",
    "email": "${JIRA_EMAIL}",
    "username": "${JIRA_USERNAME}",
    "api_token": "${JIRA_API_TOKEN}",
    "default_project": "${JIRA_DEFAULT_PROJECT}",
    "sync_bug_source": true,
    "sync_days": 2,
    "projects": {}
  },
  "github": {
    "default_base_branch": "main",
    "token": "${GITHUB_TOKEN}"
  }
}
EOF
  echo "Created config/integrations.json (edit to add your projects)"
else
  echo "Skipped config/integrations.json (already exists)"
fi

if [ ! -f "$ROOT/config/agents.json" ]; then
  cat > "$ROOT/config/agents.json" << 'EOF'
{
  "agents": {
    "claude": {
      "name": "Claude Code",
      "description": "Anthropic's agentic coding assistant. Reads SKILL.md files, executes slash commands, and drives the full bug-fix pipeline autonomously.",
      "model": "claude-sonnet-4-6",
      "provider": "Anthropic",
      "capabilities": ["code", "terminal", "file_edit", "git", "web_search"],
      "command": "claude --dangerously-skip-permissions"
    },
    "opencode": {
      "name": "OpenCode",
      "description": "Open-source AI coding agent with multi-model support. Compatible with any OpenAI-compatible backend.",
      "model": "opencode/ox-alpha",
      "provider": "OpenCode",
      "capabilities": ["code", "terminal", "file_edit"],
      "command": "opencode"
    }
  }
}
EOF
  echo "Created config/agents.json"
else
  echo "Skipped config/agents.json (already exists)"
fi

# ── Tool settings files (only created if missing) ─────────────────────────────

if [ ! -f "$ROOT/.claude/settings.local.json" ]; then
  cat > "$ROOT/.claude/settings.local.json" << 'EOF'
{
  "permissions": {
    "allow": []
  }
}
EOF
  echo "Created .claude/settings.local.json"
else
  echo "Skipped .claude/settings.local.json (already exists)"
fi

if [ ! -f "$ROOT/.opencode/opencode.jsonc" ]; then
  cat > "$ROOT/.opencode/opencode.jsonc" << 'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode/ox-alpha"
}
EOF
  echo "Created .opencode/opencode.jsonc"
else
  echo "Skipped .opencode/opencode.jsonc (already exists)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Setup complete — next steps"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo " 1. Fill in .env with your credentials"
echo "    → Sentry, Jira, GitHub tokens + any app secrets"
echo ""
echo " 2. Edit config/repositories.json"
echo "    → Replace example repos with your actual repos"
echo "    → Set git_url, base_branch, copy_files, venv, etc."
echo ""
echo " 3. Edit config/integrations.json"
echo "    → Add your Sentry projects and Jira projects"
echo ""
echo " 4. Clone your repos into workspace/"
echo "    → git clone <git_url> workspace/<repo-id>"
echo ""
echo " 5. Build repo context (run once per repo)"
echo "    → /repo-context              (all repos)"
echo "    → /repo-context <repo-id>    (single repo)"
echo ""
echo " 6. Start the app"
echo "    → ./run.sh"
echo ""
echo " 7. Open the UI and start a session"
echo "    → /fix-bug <bug-id>          fix a bug end-to-end"
echo "    → /list-bugs source=sentry   fetch latest bugs"
echo "    → /create-plan <requirement> plan a feature"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

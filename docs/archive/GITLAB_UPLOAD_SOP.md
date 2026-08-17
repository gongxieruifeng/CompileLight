# GitLab Upload SOP

This SOP is for publishing the core implementation of `ReduceTokenAgent` into the GitLab repository `AgentFSM/Project`.

Configured target:

```text
Repository browser URL: https://git.kuainiujinke.com/ai/agent-FSM
Repository SSH URL:     git@git.kuainiujinke.com:ai/agent-FSM.git
Default branch:         master
Target subdirectory:    Project/
```

## Quick Commands For Later Updates

Replace the two paths before running:

```bash
export REDUCE_TOKEN_AGENT_SRC="/Users/xieruifeng.x.gx/Desktop/ProjectToBuildPipelineAgent/WorkSpace/ReduceTokenAgent"
export AGENT_FSM_CLONE="/Users/xieruifeng.x.gx/Desktop/ProjectToBuildPipelineAgent/WorkSpace/AgentFSM"
```

Sync one file:

```bash
rsync -av "$REDUCE_TOKEN_AGENT_SRC/src/reduce_token_agent/control_plane/final_response.py" \
  "$AGENT_FSM_CLONE/Project/src/reduce_token_agent/control_plane/final_response.py"
```

Sync one folder:

```bash
rsync -av --delete \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$REDUCE_TOKEN_AGENT_SRC/src/reduce_token_agent/control_plane/" \
  "$AGENT_FSM_CLONE/Project/src/reduce_token_agent/control_plane/"
```

Sync the full core project:

```bash
rsync -av --delete --delete-excluded \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '*.egg-info/' \
  --include '/AGENTS.md' \
  --include '/PROJECT_STRUCTURE.md' \
  --include '/README.md' \
  --include '/GITLAB_UPLOAD_SOP.md' \
  --include '/pyproject.toml' \
  --include '/environment.yml' \
  --include '/.env.example' \
  --include '/.gitignore' \
  --include '/config/***' \
  --include '/migrations/***' \
  --include '/src/***' \
  --include '/scripts/' \
  --include '/scripts/activate_registry_assets.py' \
  --include '/scripts/build_retrieval_index.py' \
  --include '/scripts/review_runtime_trace.py' \
  --include '/scripts/run_agent_task.py' \
  --include '/scripts/run_control_platform.py' \
  --include '/scripts/seed_corporate_operations_registry.py' \
  --include '/scripts/seed_customer_service_registry.py' \
  --include '/scripts/seed_financial_report_registry.py' \
  --include '/scripts/verify_asset_runtime.py' \
  --include '/scripts/verify_environment.py' \
  --include '/scripts/verify_retrieval_layer.py' \
  --include '/data/' \
  --include '/data/ASSET_EXTRACTION_SOP.md' \
  --include '/data/DATA_LAYOUT_AND_RETRIEVAL_FLOW.md' \
  --include '/data/RETRIEVAL_LAYER_SOP.md' \
  --include '/data/artifacts/' \
  --include '/data/artifacts/runtime/' \
  --include '/data/artifacts/runtime/***' \
  --include '/data/artifacts/registry/' \
  --include '/data/artifacts/registry/***' \
  --exclude '*' \
  "$REDUCE_TOKEN_AGENT_SRC/" \
  "$AGENT_FSM_CLONE/Project/"
```

Review and push:

```bash
cd "$AGENT_FSM_CLONE"
git status --short
git add Project
git commit -m "Add ReduceTokenAgent core implementation"
git push origin master
```

The configured GitLab default branch is `master`.

## What Counts As Core Implementation

Upload these files and folders:

```text
AGENTS.md
PROJECT_STRUCTURE.md
README.md
GITLAB_UPLOAD_SOP.md
pyproject.toml
environment.yml
.env.example
.gitignore
config/
migrations/
src/
data/artifacts/runtime/
data/artifacts/registry/
data/ASSET_EXTRACTION_SOP.md
data/DATA_LAYOUT_AND_RETRIEVAL_FLOW.md
data/RETRIEVAL_LAYER_SOP.md
scripts/activate_registry_assets.py
scripts/build_retrieval_index.py
scripts/review_runtime_trace.py
scripts/run_agent_task.py
scripts/run_control_platform.py
scripts/seed_corporate_operations_registry.py
scripts/seed_customer_service_registry.py
scripts/seed_financial_report_registry.py
scripts/verify_asset_runtime.py
scripts/verify_environment.py
scripts/verify_retrieval_layer.py
```

Rationale:

- `src/` contains the actual Control Plane, LangGraph executor, System2, registry, retrieval, trace, LLM, and asset runtime logic.
- `migrations/` defines the local database schema and is required to rebuild state.
- `data/artifacts/runtime/` and `data/artifacts/registry/` contain reusable asset definitions needed by the current PoC.
- `scripts/` keeps only operational entrypoints needed to run, seed, verify, review, and build indexes.
- `data/*.md` keeps the extraction and retrieval operating rules that explain how assets and indexes should be maintained.

## What Must Not Be Uploaded

Do not upload these files or folders:

```text
.conda/
.env
.idea/
.vscode/
.DS_Store
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
build/
dist/
data/db/*.sqlite3
data/db/*.sqlite3-*
data/runtime/
data/traces/
data/reports/
logs/
tests/
```

Rationale:

- `.conda/`, caches, IDE files, and OS metadata are local machine state.
- `.env` can contain local endpoints or secrets.
- SQLite database files, runtime artifacts, runtime traces, and review reports are generated operational state.
- `tests/` is intentionally excluded here because this SOP targets upload of implementation code only. If GitLab should also host the long-term validation suite later, upload `tests/` in a separate commit and keep runtime/generated test outputs excluded.

## First-Time GitLab Setup

You need to provide one of the following repository URLs:

```text
SSH:   git@git.kuainiujinke.com:ai/agent-FSM.git
HTTPS: https://git.kuainiujinke.com/ai/agent-FSM.git
```

Recommended SSH setup:

```bash
ssh -T git@git.kuainiujinke.com
```

If SSH is not configured, create or reuse an SSH key and add the public key to GitLab:

```bash
ssh-keygen -t ed25519 -C "<your_email>"
cat ~/.ssh/id_ed25519.pub
```

GitLab path: `Preferences -> SSH Keys -> Add new key`.

Clone the repository:

```bash
git clone git@git.kuainiujinke.com:ai/agent-FSM.git
cd AgentFSM
mkdir -p Project
```

If the remote repository is empty and has no branch yet:

```bash
git checkout -b master
mkdir -p Project
```

Then run the full core project sync command from the first section.

## Verification Before Push

Run these checks from the source project before syncing:

```bash
cd "$REDUCE_TOKEN_AGENT_SRC"
conda activate ./.conda
python scripts/verify_environment.py
ruff check .
mypy src
pytest
```

After syncing into `AgentFSM/Project`, run a quick file audit from the GitLab clone:

```bash
cd "$AGENT_FSM_CLONE"
git status --short
find Project -path '*/.conda/*' -o -path '*/data/traces/*' -o -path '*/data/runtime/*' -o -path '*/data/reports/*' -o -name '*.sqlite3'
```

The `find` command should print nothing. If it prints files, remove those generated files from `Project` before committing.

## Commit And Push

```bash
cd "$AGENT_FSM_CLONE"
git status --short
git add Project
git commit -m "Add ReduceTokenAgent core implementation"
git push origin master
```

For later incremental updates, run the appropriate sync command at the top of this SOP, then commit and push again.

## Information Needed From You

To let me perform the actual clone/sync/push from this machine, provide:

```text
1. A working GitLab authentication method on this machine.
2. For SSH: add this machine's public SSH key to GitLab, then retry clone/push.
3. For HTTPS: authenticate through Git credential prompts or a credential manager; do not paste tokens into chat.
4. Approval to create or reuse `/Users/xieruifeng.x.gx/Desktop/ProjectToBuildPipelineAgent/WorkSpace/AgentFSM` as the local clone.
```

Do not send passwords or personal access tokens in chat. For HTTPS, authenticate through Git credential prompts or GitLab's credential manager on your machine.

# Copilot Cloud Agent Instructions — jbaruch/nanoclaw-trusted

## What This Repository Is

`jbaruch/nanoclaw-trusted` is a **NanoClaw tile** — an installable package (managed by [`tessl`](https://tessl.io)) that ships behavioural rules and runtime skills for **trusted and main NanoClaw containers**. It is not a standalone application. It is loaded alongside the core tile (`jbaruch/nanoclaw-core`) and provides the trusted-tier layer on top of it.

The tile's two deliverables are:
1. **Rules** (`rules/*.md`) — markdown files with `alwaysApply: true` YAML frontmatter, injected into the agent's context at runtime.
2. **Skills** (`skills/*/SKILL.md`) — prose-and-action markdown that the `Skill()` tool executes inside live containers.

---

## Repository Layout

```
tile.json                        # Tile manifest: name, version, rules map, skills map
README.md                        # Auto-maintained rules/skills summary table
CHANGELOG.md                     # Chronological change log — read before adding anything
rules/                           # One .md per rule, all with alwaysApply: true frontmatter
skills/
  trusted-memory/
    SKILL.md                     # Session bootstrap + rolling memory update skill
    state-schema.md              # Documents session-state.json and sentinel contracts
    scripts/
      needs-bootstrap.py         # Exit 0 = bootstrap needed, exit 1 = skip
      register-session.py        # Atomic state + sentinel writer (fcntl.LOCK_EX)
  system-status/
    SKILL.md                     # Read-only NanoClaw health probe
    scripts/
      system-status-checks.py    # JSON-producing SQLite probe script
tests/
  conftest.py                    # load_script() helper for kebab-case imports
  test_needs_bootstrap.py
  test_register_session.py
  test_system_status_checks.py
pyproject.toml                   # pytest + ruff config (ruff scoped to tests/ only)
requirements-dev.txt             # pytest==8.3.4  ruff==0.7.4
.github/workflows/
  test.yml                       # CI: ruff lint → ruff format check → pytest
  publish-tile.yml               # On merge to main: skill review → tile lint → publish
```

---

## Build, Lint, and Test

```bash
# Install dev dependencies
python -m pip install -r requirements-dev.txt

# Lint (tests/ only — tile scripts are intentionally out-of-scope)
python -m ruff check tests/
python -m ruff format --check tests/

# Run tests
python -m pytest
```

CI (`test.yml`) runs lint first, then pytest, on every PR and every push to `main`. Both must pass before merging.

The publish workflow (`publish-tile.yml`) additionally runs:
```bash
tessl skill review --threshold 85 skills/<name>/SKILL.md   # quality gate ≥85
tessl tile lint .
```
These require the `TESSL_TOKEN` secret and only run on `main`.

---

## Coding Conventions

### Scripts
- Script filenames are **kebab-case** (e.g., `register-session.py`, `needs-bootstrap.py`). This means they cannot be imported with `import`; see the test section below.
- Every script must emit a **single-line JSON status to stdout** (per `jbaruch/coding-policy: script-delegation`). Exit codes remain the authoritative success signal; JSON is for callers that want to log or inspect.
- Scripts that perform concurrent file writes take `fcntl.LOCK_EX` on a sibling `<target>.lock` file for the full read-modify-write cycle to prevent clobbering.

### Rules
- Every rule file under `rules/` **must** start with YAML frontmatter declaring `alwaysApply: true`:
  ```markdown
  ---
  alwaysApply: true
  ---
  ```
- Cross-tile rule references use explicit wording: `the \`jbaruch/nanoclaw-core\` tile's \`rules/<name>.md\``.
- Add a corresponding entry to `tile.json` under the `"rules"` key and a row to the `README.md` rules table for every new rule file.

### Skills
- Add a corresponding entry to `tile.json` under the `"skills"` key and a row to the `README.md` skills table for every new skill.
- Installed skills (`/home/node/.claude/skills/`) are **kernel-level read-only** at container runtime — `Write`/`Edit` against them returns `EROFS`. Real changes must flow through the staging → promote (`tessl__promote-tiles`) → publish (`publish-tile.yml`) → update (`./scripts/deploy.sh`) pipeline.

### tile.json
- Bump the `"version"` field for every change shipped to `main` (the `tesslio/patch-version-publish@v1` action does this automatically on the publish workflow run).
- Keep `"entrypoint": "README.md"` present.

### CHANGELOG.md
- Add an entry under `## Unreleased` for every substantive change. The publish action moves unreleased entries to a versioned section.

---

## Test Conventions

Because script filenames are kebab-case, tests use `conftest.py::load_script()` instead of normal imports:

```python
from .conftest import load_script

module = load_script("unique_module_name", "skills/trusted-memory/scripts/needs-bootstrap.py")
```

Load a fresh module instance per test (pass a unique name) so `monkeypatch` isolates module-level constants between tests without leaking state.

Tests use `monkeypatch` to redirect all I/O paths (sentinel files, DB paths, state JSON paths) into `tmp_path`.

---

## Key Concepts for Working in This Tile

### trusted-memory skill
Manages session bootstrap and rolling memory updates for trusted containers. Two scripts:
- `needs-bootstrap.py` — compares `/tmp/session_bootstrapped` to `$CLAUDE_SESSION_ID`. Exit 0 = bootstrap needed; exit 1 = skip.
- `register-session.py` — atomically writes `/workspace/group/session-state.json` (schema_version: 1, per-session subtree + back-compat top-level `session_id`) and the sentinel at `/tmp/session_bootstrapped`.

State schema is documented in `skills/trusted-memory/state-schema.md`. Reader skills must treat unknown `schema_version > 1` as "no usable prior state".

### system-status skill
Read-only SQLite probe against `/workspace/store/messages.db`. Reports stuck scheduled tasks, row counts/DB size alerts, and recent task failures. Does **not** manage the dismiss mechanism (that lives in the admin tile). On clean pass, emits nothing.

### Memory file locations
| Path | Contents |
|------|----------|
| `/workspace/trusted/` (root) | Typed memory files: `user_*.md`, `feedback_*.md`, `project_*.md`, `reference_*.md` |
| `/workspace/trusted/MEMORY.md` | Index (max 200 lines, one line per file) |
| `/workspace/trusted/memory/daily/` | Daily cross-group log files |
| `/workspace/trusted/memory/daily_discoveries.md` | Append-only operational learnings |
| `/workspace/trusted/wiki/` | Domain knowledge (not operational memory) |
| `/workspace/trusted/highlights.md` | Weekly highlights archive |

Typed memory files go in the **root** of `/workspace/trusted/`, never under `/workspace/trusted/memory/`.

### Skill pipeline (for changes to SKILL.md or rules)
Never edit installed content directly (EROFS). Changes flow through:
1. Edit in NAS staging.
2. `tessl__promote-tiles` opens a tile-repo PR.
3. Copilot review + merge.
4. `publish-tile.yml` publishes to registry.
5. `./scripts/deploy.sh` runs `tessl update`; next container spawn picks up the new content.

---

## Errors Encountered During Onboarding

No errors encountered. The repository was self-consistent and all referenced scripts, tests, and workflows were present.

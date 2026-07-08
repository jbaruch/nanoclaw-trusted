# Copilot Cloud Agent Instructions — jbaruch/nanoclaw-trusted

## What This Repository Is

`jbaruch/nanoclaw-trusted` is a **NanoClaw tile** — an installable package (managed by [`tessl`](https://tessl.io)) that ships behavioural rules and runtime skills for **trusted and main NanoClaw containers**. It is not a standalone application. It is loaded alongside the core tile (`jbaruch/nanoclaw-core`) and provides the trusted-tier layer on top of it.

The tile's two deliverables are:
1. **Rules** (`rules/*.md`) — markdown files with YAML frontmatter, injected into the agent's context at runtime. Always-on rules declare `alwaysApply: true`; conditional rules declare `alwaysApply: false` plus an `applyTo:` scope (see `README.md` and `jbaruch/coding-policy: rule-frontmatter`).
2. **Skills** (`skills/*/SKILL.md`) — prose-and-action markdown that the `Skill()` tool executes inside live containers.

---

## Repository Layout

```
tile.json                        # Tile manifest: name, version, rules map, skills map
README.md                        # Auto-maintained rules/skills summary table
CHANGELOG.md                     # Chronological change log — read before adding anything
rules/                           # One .md per rule; frontmatter is alwaysApply: true
                                 # or alwaysApply: false + applyTo: (conditional)
skills/
  trusted-memory/
    SKILL.md                     # Session bootstrap + rolling memory update skill
    state-schema.md              # Documents session-state.json and sentinel contracts
    scripts/
      needs-bootstrap.py         # Exit 0 = bootstrap needed, exit 1 = skip
      register-session.py        # Atomic state + sentinel writer (fcntl.LOCK_EX)
      append-to-daily-log.py     # Locked, dedup-filtered daily-log appender
      append-daily-discovery.py  # Locked, dedup-filtered discoveries appender
      memory_write.py            # Helper module (not a CLI entrypoint): shared
                                 # write_atomic + dedup_filter primitives. snake_case
                                 # on purpose — siblings `import memory_write`;
                                 # kebab-case would break the import
  system-status/
    SKILL.md                     # Read-only NanoClaw health probe
    scripts/
      system-status-checks.py    # JSON-producing SQLite probe script
  status/
    SKILL.md                     # /status — container uptime + environment snapshot
    scripts/
      container-uptime.py        # JSON-producing uptime probe (adopted from nanoclaw-core)
tests/
  conftest.py                    # load_script() helper for kebab-case imports
  test_needs_bootstrap.py
  test_register_session.py
  test_append_to_daily_log.py
  test_append_daily_discovery.py
  test_memory_write.py
  test_system_status_checks.py
  test_container_uptime.py
pyproject.toml                   # pytest + ruff config (ruff scoped to tests/ only)
pyrightconfig.json               # pyright config (whole repo: scripts + tests)
requirements-dev.txt             # pytest==8.3.4  ruff==0.7.4  pyright==1.1.408
.github/workflows/
  test.yml                       # CI: ruff lint → ruff format check → pyright → pytest
  publish-tile.yml               # On merge to main: changed-skills review → tile lint
                                 # → stamp CHANGELOG → patch-version publish
```

---

## Build, Lint, and Test

```bash
# Install dev dependencies
python -m pip install -r requirements-dev.txt

# Lint (tests/ only — tile scripts are intentionally out-of-scope)
python -m ruff check tests/
python -m ruff format --check tests/

# Type-check (whole repo: scripts + tests, per pyrightconfig.json)
python -m pyright

# Run tests
python -m pytest
```

CI (`test.yml`) runs ruff lint, then pyright at zero findings, then pytest, on every PR and every push to `main`. All three must pass before merging.

The publish workflow (`publish-tile.yml`) additionally runs, in order:
```bash
tessl skill review --threshold 85 skills/<name>/SKILL.md   # changed skills only (git diff loop)
tessl tile lint .
# then: stamp CHANGELOG heading → tesslio/patch-version-publish@v1
```
These require the `TESSL_TOKEN` secret and only run on `main`.

---

## Coding Conventions

### Scripts
- **CLI entrypoint** filenames are **kebab-case** (e.g., `register-session.py`, `needs-bootstrap.py`). This means they cannot be imported with `import`; see the test section below.
- **Helper modules** imported by sibling scripts are **snake_case** (e.g., `memory_write.py`, imported as `import memory_write`). This is a deliberate exception to the kebab-case rule — do not rename it to kebab-case or the imports break. The kebab-case rule governs entrypoints only.
- Every script must emit a **single-line JSON status to stdout** (per `jbaruch/coding-policy: script-delegation`). Exit codes remain the authoritative success signal; JSON is for callers that want to log or inspect.
- Scripts that perform concurrent file writes take `fcntl.LOCK_EX` on a sibling `<target>.lock` file for the full read-modify-write cycle to prevent clobbering.

### Rules
- Every rule file under `rules/` **must** start with YAML frontmatter. Always-on rules declare `alwaysApply: true`; conditional rules declare `alwaysApply: false` plus an `applyTo: "<glob list> — <natural-language clause>"` scope:
  ```markdown
  ---
  alwaysApply: false
  applyTo: "** — when querying messages.db or referencing its column names"
  ---
  ```
- Pick the scope per `jbaruch/coding-policy: rule-frontmatter` — stay `alwaysApply: true` when the rule mixes file-bound and broad guidance.
- Cross-tile rule references use explicit wording: `the \`jbaruch/nanoclaw-core\` tile's \`rules/<name>.md\``.
- Add a corresponding entry to `tile.json` under the `"rules"` key and a row to the `README.md` rules table for every new rule file.

### Skills
- Add a corresponding entry to `tile.json` under the `"skills"` key and a row to the `README.md` skills table for every new skill.
- Installed skills (`/home/node/.claude/skills/`) are **kernel-level read-only** at container runtime — `Write`/`Edit` against them returns `EROFS`. Real changes must flow through the staging → promote (`tessl__promote-tiles`) → publish (`publish-tile.yml`) → update (`./scripts/deploy.sh`) pipeline.

### tile.json
- Bump the `"version"` field for every change shipped to `main` (the `tesslio/patch-version-publish@v1` action does this automatically on the publish workflow run).
- Keep `"entrypoint": "README.md"` present.

### CHANGELOG.md
- Add an **un-headed `### ` entry block** at the top of the file (below the header comment) for every substantive change — no `## Unreleased` heading, ever. The publish workflow's stamp-changelog step inserts the `## <version> — <date>` heading above the un-headed blocks before publishing.

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
Manages session bootstrap and rolling memory updates for trusted containers. Four CLI entrypoints plus one helper module:
- `needs-bootstrap.py` — compares `/tmp/session_bootstrapped` to `$CLAUDE_SESSION_ID`. Exit 0 = bootstrap needed; exit 1 = skip.
- `register-session.py` — atomically writes `/workspace/group/session-state.json` (schema_version: 1, per-session subtree + back-compat top-level `session_id`) and the sentinel at `/tmp/session_bootstrapped`.
- `append-to-daily-log.py` — appends line entries to the daily cross-group log under `fcntl.LOCK_EX`, dedup-filtered against existing lines.
- `append-daily-discovery.py` — appends the four-line discovery block to `daily_discoveries.md` under the same lock; dedup key excludes the timestamp header so retries are idempotent; rejects CR/LF in field values.
- `memory_write.py` — helper module (`import memory_write`), the single home for `write_atomic` and `dedup_filter`.

State schema is documented in `skills/trusted-memory/state-schema.md`. Reader skills must treat unknown `schema_version > 1` as "no usable prior state".

### system-status skill
Read-only SQLite probe against `/workspace/store/messages.db`. Reports stuck scheduled tasks, row counts/DB size alerts, and recent task failures. Does **not** manage the dismiss mechanism (that lives in the admin tile). On clean pass, emits nothing.

### status skill
`/status` — container uptime + environment snapshot via `container-uptime.py`. Adopted from nanoclaw-core (trusted-tier placement closes an environment-recon gap for untrusted groups). Complements `system-status`: `status` reports this container, `system-status` probes the orchestrator DB.

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

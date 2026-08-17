"""Tests for `skills/trusted-memory/scripts/migrate-addresses-block.py`.

Builds the canonical `## Addresses` block programmatically in a tmp file (no
fixtures checked in, per `jbaruch/coding-policy: testing-standards`) and pins
the owner-side migration contract:

  - a block below the current version is restamped, every other line untouched
  - the legacy pre-versioned block (no `schema_version` line) gains one
  - a block already current is left byte-identical and reports `migrated: false`
  - a block ABOVE the current version refuses — rewriting it would downgrade
    state a newer owner wrote
  - no key is added: `home_metro` has no default
  - values outside the block are never touched
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import load_script

SCRIPT_REL = "skills/trusted-memory/scripts/migrate-addresses-block.py"


@pytest.fixture
def migrate_addresses_block(tmp_path):
    return load_script(f"migrate_addresses_block_{tmp_path.name}", SCRIPT_REL)


def _profile(tmp_path, block: str, *, prose: str = "") -> Path:
    path = tmp_path / "user_profile.md"
    path.write_text(f"# Owner Profile\n{prose}\n{block}", encoding="utf-8")
    return path


V1_BLOCK = """\
## Addresses
<!-- canonical, machine-read by travel tile; schema v1 — see trusted-memory state-schema.md -->
- schema_version: 1
- current_home: 1040 Pine Creek Dr, Arrington, TN 37014
- home_airport: BNA
- new_home_wip: 1835 Burke Hollow Rd, Nolensville, TN 37135

## See also

- nothing here
"""


def _run(module, path):
    code = module.main(["--profile", str(path)])
    return code


def test_v1_block_is_restamped(migrate_addresses_block, tmp_path, capsys):
    path = _profile(tmp_path, V1_BLOCK)
    assert _run(migrate_addresses_block, path) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "migrated": True,
        "from": 1,
        "to": 2,
        "path": str(path),
    }
    assert "- schema_version: 2\n" in path.read_text()


def test_migration_touches_no_other_value(migrate_addresses_block, tmp_path, capsys):
    path = _profile(tmp_path, V1_BLOCK)
    _run(migrate_addresses_block, path)
    capsys.readouterr()
    text = path.read_text()
    assert "- current_home: 1040 Pine Creek Dr, Arrington, TN 37014\n" in text
    assert "- home_airport: BNA\n" in text
    assert "- new_home_wip: 1835 Burke Hollow Rd, Nolensville, TN 37135\n" in text
    # `home_metro` has no default — it stays absent until the operator names one.
    assert "home_metro" not in text
    # Content outside the block is untouched.
    assert "## See also" in text
    assert "- nothing here" in text


def test_provenance_comment_follows_the_stamp(migrate_addresses_block, tmp_path, capsys):
    # A comment claiming v1 above a v2 stamp sends the next reader to the wrong
    # section of the docs.
    path = _profile(tmp_path, V1_BLOCK)
    _run(migrate_addresses_block, path)
    capsys.readouterr()
    assert "schema v2 —" in path.read_text()


def test_legacy_unversioned_block_gains_a_stamp(migrate_addresses_block, tmp_path, capsys):
    path = _profile(
        tmp_path,
        "## Addresses\n- current_home: 12 Example St\n- home_airport: BNA\n",
    )
    assert _run(migrate_addresses_block, path) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["migrated"] is True
    assert payload["from"] is None
    text = path.read_text()
    assert text.index("- schema_version: 2") < text.index("- current_home:")


def test_current_block_is_a_no_op(migrate_addresses_block, tmp_path, capsys):
    block = V1_BLOCK.replace("- schema_version: 1", "- schema_version: 2").replace(
        "schema v1", "schema v2"
    )
    path = _profile(tmp_path, block)
    before = path.read_bytes()
    assert _run(migrate_addresses_block, path) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["migrated"] is False
    assert payload["from"] == 2
    assert path.read_bytes() == before


def test_is_idempotent(migrate_addresses_block, tmp_path, capsys):
    # The bootstrap step runs this every session; a second run must change nothing.
    path = _profile(tmp_path, V1_BLOCK)
    _run(migrate_addresses_block, path)
    capsys.readouterr()
    after_first = path.read_bytes()
    assert _run(migrate_addresses_block, path) == 0
    assert json.loads(capsys.readouterr().out)["migrated"] is False
    assert path.read_bytes() == after_first


def test_future_version_refuses(migrate_addresses_block, tmp_path, capsys):
    path = _profile(tmp_path, V1_BLOCK.replace("- schema_version: 1", "- schema_version: 99"))
    before = path.read_bytes()
    assert _run(migrate_addresses_block, path) == 1
    err = capsys.readouterr().err
    assert "above this writer's" in err
    assert "upgrading this plugin" in err
    assert path.read_bytes() == before


def test_unreadable_version_refuses(migrate_addresses_block, tmp_path, capsys):
    path = _profile(tmp_path, V1_BLOCK.replace("- schema_version: 1", "- schema_version: draft"))
    before = path.read_bytes()
    assert _run(migrate_addresses_block, path) == 1
    assert "unreadable schema_version" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_missing_block_is_an_actionable_error(migrate_addresses_block, tmp_path, capsys):
    path = tmp_path / "user_profile.md"
    path.write_text("# Owner Profile\n\nProse only.\n", encoding="utf-8")
    assert _run(migrate_addresses_block, path) == 1
    assert "no `## Addresses` block" in capsys.readouterr().err


def test_missing_profile_is_an_actionable_error(migrate_addresses_block, tmp_path, capsys):
    assert _run(migrate_addresses_block, tmp_path / "nope.md") == 1
    assert "owner profile not found" in capsys.readouterr().err


def test_a_schema_version_outside_the_block_is_ignored(migrate_addresses_block, tmp_path, capsys):
    # Only the canonical block is migrated — a `schema_version:` line in prose or
    # another section is somebody else's state.
    path = _profile(tmp_path, V1_BLOCK, prose="\n- schema_version: 7\n")
    assert _run(migrate_addresses_block, path) == 0
    capsys.readouterr()
    text = path.read_text()
    assert "- schema_version: 7\n" in text
    assert "- schema_version: 2\n" in text


def test_env_override(migrate_addresses_block, tmp_path, monkeypatch, capsys):
    path = _profile(tmp_path, V1_BLOCK)
    monkeypatch.setenv("USER_PROFILE_PATH", str(path))
    assert migrate_addresses_block.main([]) == 0
    assert json.loads(capsys.readouterr().out)["migrated"] is True

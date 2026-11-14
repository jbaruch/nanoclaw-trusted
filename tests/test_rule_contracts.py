"""Published rule budgets and task scopes for trusted context."""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_every_trusted_rule_fits_two_kilobytes():
    oversized = {
        path.name: path.stat().st_size
        for path in (REPO_ROOT / "rules").glob("*.md")
        if path.stat().st_size > 2000
    }
    assert oversized == {}


def test_core_verification_rules_are_not_published_twice():
    manifest = json.loads((REPO_ROOT / ".tessl-plugin/plugin.json").read_text())
    for name in ("ground-truth-trusted", "verification-protocol"):
        assert f"rules/{name}.md" not in manifest["rules"]
        assert not (REPO_ROOT / "rules" / f"{name}.md").exists()


@pytest.mark.parametrize(
    ("rule", "triggers"),
    [
        ("compaction-aware-summaries", ("compaction", "summaries")),
        ("daily-discoveries-rule", ("learning", "daily_discoveries.md")),
        ("context-bootstrap-bg-agents", ("background", "Agent")),
        ("identity-compaction-recovery", ("compaction", "persona context")),
        ("session-bootstrap", ("session start", "bootstrap")),
        ("wiki-awareness", ("source material", "answering questions", "reusable answers")),
    ],
)
def test_task_specific_rules_declare_all_triggers(rule: str, triggers: tuple[str, ...]):
    text = (REPO_ROOT / "rules" / f"{rule}.md").read_text()
    frontmatter = text.split("---", 2)[1].splitlines()
    assert "alwaysApply: false" in frontmatter
    scope = next(line for line in frontmatter if line.startswith("applyTo: "))
    assert scope.startswith('applyTo: "** — ')
    for trigger in triggers:
        assert trigger in scope


def test_google_trust_boundaries_remain_in_loaded_rules():
    boundary = (REPO_ROOT / "rules/container-trust-levels.md").read_text()
    assert "alwaysApply: true" in boundary
    assert "Never read a Google key from the environment" in boundary
    assert "A trusted non-main container has no email-verification path" in boundary
    assert "Report the claim as unverified" in boundary
    assert "do not reach for another route" in boundary


@pytest.mark.parametrize(
    ("rule", "reference"),
    [
        ("messages-db-schema", "skills/system-status/references/messages-db-schema.md"),
        ("container-trust-levels", "skills/google-ops/references/trusted-verification.md"),
        ("no-silent-defer", "skills/trusted-memory/references/skip-summary-schema.md"),
    ],
)
def test_rule_references_ship_inside_manifest_skills(rule: str, reference: str):
    text = (REPO_ROOT / "rules" / f"{rule}.md").read_text()
    assert reference in text
    assert (REPO_ROOT / reference).is_file()
    manifest = json.loads((REPO_ROOT / ".tessl-plugin/plugin.json").read_text())
    assert any(reference.startswith(f"{skill}/") for skill in manifest["skills"])

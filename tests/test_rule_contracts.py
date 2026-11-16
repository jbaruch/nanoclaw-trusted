"""Trusted-rule budget and contracts in the host's installed layout."""

import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_plugin_has_no_generated_agent_entrypoints():
    for name in ("AGENTS.md", "CLAUDE.md"):
        assert not (REPO_ROOT / name).exists(), f"Remove generated agent entrypoint: {name}"


def test_every_trusted_rule_fits_two_kilobytes():
    oversized = {
        path.name: path.stat().st_size
        for path in (REPO_ROOT / "rules").glob("*.md")
        if path.stat().st_size > 2000
    }
    assert oversized == {}


@pytest.fixture
def installed_context(tmp_path):
    # Host ef8cf4d src/volume-mounts.ts:715-759,830-834 copies complete skills
    # and concatenates rules. No checkout-relative reads by the consumer below.
    manifest = json.loads((REPO_ROOT / ".tessl-plugin/plugin.json").read_text())
    native = tmp_path / "home/node/.claude"
    for skill in manifest["skills"]:
        shutil.copytree(REPO_ROOT / skill, native / "skills" / f"tessl__{Path(skill).name}")
    startup = native / ".tessl/RULES.md"
    startup.parent.mkdir(parents=True)
    startup.write_text("\n\n---\n\n".join((REPO_ROOT / p).read_text() for p in manifest["rules"]))
    return native, startup.read_text()


def test_installed_verification_retains_triggers_and_ipc_readback(installed_context):
    _, startup = installed_context
    assert (
        'alwaysApply: false\napplyTo: "** — when answering substantive trusted-tier questions '
        'or producing claims that need verification"\n---\n\n# Ground Truth — Trusted Extensions'
    ) in startup
    assert "alwaysApply: true\n---\n\n## Verification Protocol" in startup
    for directive in (
        "# Ground Truth — Trusted Extensions",
        "answering substantive trusted-tier questions or producing claims that need verification",
        "google-calendar.py events-list",
        "google-tasks.py list",
        'Skill(skill: "google-ops")',
        "/home/node/.claude/skills/tessl__google-ops/scripts/<script>.py",
        "`jbaruch/nanoclaw-admin` `rules/google-access.md` owns op names",
        "Never read Google keys from the environment or send an `Authorization` header",
        "a container credential is a bug, never a fallback",
        "Calendar/Tasks scripts ship on main and trusted without admin co-loading",
        "Trusted access is read-only",
        "Sanitizing Gmail-fetch ships in admin, baseline on main only",
        "Trusted non-main has no email-verification path",
        "never raw-fetch",
        "On `access_restricted`, report the claim unverified",
        "do not assert it or try another route",
        "An unauthenticated 404 proves only lack of visibility",
        "Recheck through authenticated `gh` before asserting non-existence",
        "or retracting an existence claim",
        "`Agent` sub-agents share the container, `GITHUB_TOKEN` and script mounts",
        "Chain tools to compute answers; do not ask for computable inputs",
        "use Calendar destination and Maps travel time to compute departure",
        "subtract the reminder offset from departure, not event start",
        "These sources are unavailable in untrusted containers",
        "## Verification Protocol",
        "/workspace/ipc/messages/",
        "file exists at the expected path",
        "read back",
        "payload matches what you intended",
    ):
        assert directive in startup


def test_installed_skip_summary_read_gate_and_recovery(installed_context):
    native, startup = installed_context
    path = "/home/node/.claude/skills/tessl__trusted-memory/references/skip-summary-schema.md"
    assert f"read in full with the native Read tool: `{path}`" in startup
    assert "Missing or unreadable reference stops summary processing" in startup
    assert "Never `@`-import it" in startup
    reference = native / Path(path).relative_to("/home/node/.claude")
    contract = reference.read_text()
    assert (
        contract
        == (REPO_ROOT / "skills/trusted-memory/references/skip-summary-schema.md").read_text()
    )
    for directive in (
        "deletes the file only after a successful send for a supported version",
        "unrecognised `schema_version` send an actionable unsupported-version notice",
        "Include the file path, observed version, supported version `1`",
        "Retain the file for recovery, even after the notice is sent",
        "do not render guessed fields, migrate, rewrite, or delete it",
        "If sending fails, report that failure to the caller and retain the file",
    ):
        assert directive in contract

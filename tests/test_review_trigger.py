"""Exercise the fleet-review dispatch condition for PRs with and without secrets."""

from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    ("actor", "head_repo", "expected"),
    [
        ("dependabot[bot]", "jbaruch/nanoclaw-trusted", False),
        ("dependabot[bot]", "contributor/nanoclaw-trusted", False),
        ("renovate[bot]", "jbaruch/nanoclaw-trusted", True),
        ("renovate[bot]", "contributor/nanoclaw-trusted", False),
        ("contributor", "jbaruch/nanoclaw-trusted", True),
        ("contributor", "contributor/nanoclaw-trusted", False),
    ],
)
def test_review_dispatch_requires_actions_secret_access(actor, head_repo, expected):
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/review-trigger.yml"
    ).read_text()
    condition = " ".join(workflow.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0].split())
    github = SimpleNamespace(
        actor=actor,
        repository="jbaruch/nanoclaw-trusted",
        event=SimpleNamespace(
            pull_request=SimpleNamespace(
                head=SimpleNamespace(repo=SimpleNamespace(full_name=head_repo))
            )
        ),
    )
    # This condition uses comparisons and boolean operators shared with Python.
    expression = condition.replace("&&", " and ").replace("||", " or ")
    assert eval(expression, {"__builtins__": {}}, {"github": github}) is expected

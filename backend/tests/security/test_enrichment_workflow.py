"""The optional research crawl stays manual and fail-closed when secrets are absent."""

from pathlib import Path

import yaml


def workflow():
    path = Path(__file__).resolve().parents[3] / ".github/workflows/enrichment-incremental.yml"
    # BaseLoader keeps GitHub's `on` key a string (YAML 1.1 would coerce it to True).
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def test_enrichment_remains_manual_only():
    assert set(workflow()["on"]) == {"workflow_dispatch"}


def test_enrichment_secret_is_not_referenced_in_if_expressions():
    job = workflow()["jobs"]["crawl"]
    assert "if" not in job
    assert job["env"]["HAS_PRODUCTION_DATABASE"] == "${{ secrets.PRODUCTION_DATABASE_URL != '' }}"
    assert all("secrets." not in step.get("if", "") for step in job["steps"])


def test_enrichment_setup_and_database_steps_are_guarded():
    job = workflow()["jobs"]["crawl"]
    notice, *guarded = job["steps"]
    assert notice["if"] == "${{ env.HAS_PRODUCTION_DATABASE != 'true' }}"
    assert notice["working-directory"] == "."  # no checkout/backend directory yet
    assert all("env.HAS_PRODUCTION_DATABASE == 'true'" in step["if"] for step in guarded)
    assert all("secrets.PRODUCTION_DATABASE_URL" not in str(step) for step in guarded[:3])
    assert "always()" in guarded[-1]["if"]

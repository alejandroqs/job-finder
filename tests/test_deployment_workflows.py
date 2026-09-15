"""Static safety contracts; these do not execute GitHub Actions or AWS."""

from pathlib import Path
import re

import yaml


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def load_workflow(name):
    # BaseLoader preserves GitHub's `on` key (YAML 1.1 treats it as True).
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def run_steps(workflow):
    return [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "run" in step
    ]


def test_push_deployment_never_invokes_lambda():
    deployment = load_workflow("deploy.yml")
    assert set(deployment["on"]) == {"push"}
    for step in run_steps(deployment):
        assert not re.search(r"\baws\s+lambda\s+invoke\b", step["run"])
    assert any("get-function-configuration" in step["run"] for step in run_steps(deployment))


def test_scan_is_manual_and_requires_explicit_publishing_on_main():
    scan = load_workflow("run-scan.yml")
    assert set(scan["on"]) == {"workflow_dispatch"}
    consent = scan["on"]["workflow_dispatch"]["inputs"]["publish_notifications"]
    assert consent["type"] == "boolean"
    assert consent["default"] == "false"
    for job in scan["jobs"].values():
        assert job["if"] == "github.ref == 'refs/heads/main' && inputs.publish_notifications"


def test_manual_invocation_has_one_attempt_and_checks_function_errors():
    scan = load_workflow("run-scan.yml")
    invocations = [step for step in run_steps(scan) if "aws lambda invoke" in step["run"]]
    assert len(invocations) == 1
    step = invocations[0]
    assert step["env"]["AWS_MAX_ATTEMPTS"] == "1"
    assert step["env"]["AWS_RETRY_MODE"] == "standard"
    assert "--invocation-type RequestResponse" in step["run"]
    assert "--cli-read-timeout 960" in step["run"]
    assert 'jq -e' in step["run"]
    assert 'has("FunctionError") | not' in step["run"]
    assert '.statusCode == 200' in step["run"]


def test_production_workflows_share_non_cancelling_concurrency_group():
    deployment = load_workflow("deploy.yml")
    scan = load_workflow("run-scan.yml")
    assert deployment["concurrency"] == scan["concurrency"]
    assert deployment["concurrency"]["group"]
    assert deployment["concurrency"]["cancel-in-progress"] == "false"

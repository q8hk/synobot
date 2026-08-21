"""Dependency-free static contracts for the GitHub Actions workflows."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_workflows_have_triggers_least_permissions_and_concurrency():
    for workflow in WORKFLOWS.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert re.search(r"(?m)^name: .+$", text), workflow
        assert re.search(r"(?m)^on:$", text), workflow
        assert re.search(r"(?m)^permissions:$", text), workflow
        assert re.search(r"(?m)^concurrency:$", text), workflow
        assert "actions/checkout@v1" not in text
        assert "actions/checkout@v2" not in text


def test_pull_requests_build_but_never_publish_container():
    text = read("docker-build.yml")
    assert "pull_request:" in text
    assert "docker/build-push-action@v7" in text
    assert "push: false" in text
    assert "docker/login-action" not in text


def test_release_is_tag_only_multi_platform_and_hardened():
    text = read("main.yml")
    assert '      - "v*"' in text
    assert "linux/amd64,linux/arm64" in text
    assert "ghcr.io/${{ github.repository }}" in text
    assert "aquasecurity/trivy-action@0.35.0" in text
    assert "sbom: true" in text
    assert "provenance: mode=max" in text
    assert "packages: write" in text
    assert "id-token: write" in text


def test_dockerhub_is_optional_and_secrets_are_not_embedded():
    text = read("main.yml")
    condition = "env.DOCKERHUB_USERNAME != '' && env.DOCKERHUB_TOKEN != ''"
    assert text.count(condition) == 3
    assert "password: ${{ env.DOCKERHUB_TOKEN }}" in text
    assert "acidpop/synobot" in text


def test_codeql_uses_supported_node24_action():
    text = read("codeql-analysis.yml")
    assert "github/codeql-action/init@v4" in text
    assert "github/codeql-action/analyze@v4" in text
    assert "security-events: write" in text


def test_dependabot_covers_all_dependency_sources():
    text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    for ecosystem in ("pip", "github-actions", "docker"):
        assert f"package-ecosystem: {ecosystem}" in text

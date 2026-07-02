from __future__ import annotations

from types import ModuleType
from typing import Any

from fixbot.defaults import bitbucket, datadog, github, github_issues, gitlab, grafana, jira, linear

MCP_ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "observability": {"name": datadog.NAME, "factory": datadog.get_default},
    "issue_tracker": {"name": linear.NAME, "factory": linear.get_default},
    "code_host": {"name": github.NAME, "factory": github.get_default},
}

CODE_HOST_PROVIDERS: dict[str, ModuleType] = {
    "bitbucket": bitbucket,
    "github": github,
    "gitlab": gitlab,
}

ISSUE_TRACKER_PROVIDERS: dict[str, ModuleType] = {
    "github": github_issues,
    "jira": jira,
    "linear": linear,
}

OBSERVABILITY_PROVIDERS: dict[str, ModuleType] = {
    "datadog": datadog,
    "grafana": grafana,
}


def server_config_haystack(server: dict[str, Any]) -> str:
    """Flatten all keys and string values of an MCP server config into one
    lowercased string, for provider-detection heuristics (``looks_like``).

    Captures env-var keys (e.g. ``GITLAB_PERSONAL_ACCESS_TOKEN``) as well as
    header/env/url values (e.g. ``${GITHUB_TOKEN}``, ``mcp.linear.app``).
    """
    parts: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                parts.append(str(key))
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
        else:
            parts.append(str(obj))

    _walk(server)
    return " ".join(parts).lower()


def get_code_host_provider(code_host_type: str) -> ModuleType:
    provider = CODE_HOST_PROVIDERS.get(code_host_type)
    if provider is None:
        available = ", ".join(sorted(CODE_HOST_PROVIDERS))
        raise ValueError(f"Unknown code_host_type '{code_host_type}'. Available: {available}")
    return provider


def get_issue_tracker_provider(issue_tracker_type: str) -> ModuleType:
    provider = ISSUE_TRACKER_PROVIDERS.get(issue_tracker_type)
    if provider is None:
        available = ", ".join(sorted(ISSUE_TRACKER_PROVIDERS))
        raise ValueError(
            f"Unknown issue_tracker_type '{issue_tracker_type}'. Available: {available}"
        )
    return provider


def get_observability_provider(observability_type: str) -> ModuleType:
    provider = OBSERVABILITY_PROVIDERS.get(observability_type)
    if provider is None:
        available = ", ".join(sorted(OBSERVABILITY_PROVIDERS))
        raise ValueError(
            f"Unknown observability_type '{observability_type}'. Available: {available}"
        )
    return provider

"""Load the agent definition in agent/app.yaml into typed, validated objects.

The YAML file and the Markdown files it points to are the source of truth for
the CX Agent Studio app. Nothing here talks to Google Cloud, so the whole
definition can be checked in a unit test before anything is deployed.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"

# ces.googleapis.com rejects user-specified IDs outside [a-zA-Z0-9][a-zA-Z0-9-_]{4,35}
# (5 to 36 characters). We keep to the lowercase, hyphenated subset of that rule.
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{4,35}$")
_SCOPES = {"USER_QUERY", "AGENT_RESPONSE", "USER_QUERY_AND_AGENT_RESPONSE"}
_CHANNELS = {"API", "WEB_UI", "GOOGLE_TELEPHONY_PLATFORM"}
_SYSTEM_TOOLS = {"end_session", "transfer_to_agent", "customize_response"}
_VARIABLE_TYPES = {"STRING", "OBJECT", "BOOLEAN", "NUMBER", "INTEGER", "ARRAY"}
_AUTH = {"service_agent_id_token", "none"}


class ConfigError(ValueError):
    """Raised when agent/app.yaml or a file it references is invalid."""


@dataclass(frozen=True)
class AgentToolsetRef:
    """Which operations of a toolset an agent may call. Anything not listed, it can't."""

    toolset: str
    tools: list[str]


@dataclass(frozen=True)
class RemoteAgentSpec:
    """Another agent this app may delegate to over A2A, described by its agent card."""

    id: str
    name: str
    description: str
    url: str
    skills: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentSpec:
    """One agent in the app: its ID, names, instruction text, and the tools it is granted."""

    id: str
    display_name: str
    description: str
    instruction: str
    system_tools: list[str] = field(default_factory=list)
    toolsets: list[AgentToolsetRef] = field(default_factory=list)
    remote_agents: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VariableSpec:
    """A session variable the platform reads or writes (telephonyTransferCall, telephony-caller-id)."""

    name: str
    description: str
    type: str
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolsetSpec:
    """An OpenAPI toolset: the contract file, where it is served, and how the agent authenticates."""

    id: str
    display_name: str
    description: str
    open_api_schema: str
    url: str
    auth: str


@dataclass(frozen=True)
class GuardrailSpec:
    """A guardrail and the reply used when it triggers.

    kind "llm_policy" asks a model to judge (prompt); "regex" matches patterns
    deterministically (patterns); "prompt_security" is the platform's prompt guard.
    """

    id: str
    display_name: str
    description: str
    scope: str
    fail_open: bool
    prompt: str
    response: str
    kind: str = "llm_policy"
    patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DeploymentSpec:
    """A deployment of the app to one channel."""

    id: str
    display_name: str
    channel_type: str


@dataclass(frozen=True)
class RedactionSpec:
    """Cloud DLP templates that redact transcripts and logs (Part 6)."""

    inspect_template: str
    deidentify_template: str


@dataclass(frozen=True)
class AppSpec:
    """The whole app as described by agent/app.yaml."""

    app_id: str
    display_name: str
    description: str
    location: str
    language_code: str
    time_zone: str
    model: str
    root_agent: str
    agents: list[AgentSpec] = field(default_factory=list)
    variables: list[VariableSpec] = field(default_factory=list)
    toolsets: list[ToolsetSpec] = field(default_factory=list)
    remote_agents: list[RemoteAgentSpec] = field(default_factory=list)
    redaction: RedactionSpec | None = None
    guardrails: list[GuardrailSpec] = field(default_factory=list)
    deployments: list[DeploymentSpec] = field(default_factory=list)


def _check_id(value: str, what: str) -> str:
    if not _ID_PATTERN.match(value):
        raise ConfigError(f"{what} ID {value!r} must be 5-36 characters: lowercase letters, digits and hyphens")
    return value


def _read_text(base: Path, relative: str) -> str:
    path = (base / relative).resolve()
    if base.resolve() not in path.parents:
        raise ConfigError(f"{relative!r} points outside {base}")
    if not path.is_file():
        raise ConfigError(f"{relative!r} does not exist")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ConfigError(f"{relative!r} is empty")
    return text


def _url(value: str, require_urls: bool) -> str:
    """URLs may start with an environment variable, like ${TOOLS_API_URL}/v1, so no URL is hard-coded."""
    match = re.fullmatch(r"\$\{([A-Z0-9_]+)\}(.*)", value)
    if not match:
        return value
    resolved = os.environ.get(match.group(1), "")
    if require_urls and not resolved.startswith("https://"):
        raise ConfigError(f"Set {match.group(1)} to the service's https URL (terraform output)")
    return (resolved or "https://unset.invalid") + match.group(2)


def _env(value: str, require: bool) -> str:
    """Resolve ${VAR} for non-URL values such as DLP template resource names."""
    match = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", value)
    if not match:
        return value
    resolved = os.environ.get(match.group(1), "")
    if require and not resolved:
        raise ConfigError(f"Set {match.group(1)} (terraform output)")
    return resolved


def _toolsets(agent_dir: Path, raw: list[dict], require_urls: bool) -> list[ToolsetSpec]:
    out = []
    for t in raw:
        if t.get("auth", "service_agent_id_token") not in _AUTH:
            raise ConfigError(f"Toolset auth {t.get('auth')!r} must be one of {sorted(_AUTH)}")
        url = _url(t["url"], require_urls)
        contract = yaml.safe_load(_read_text(agent_dir, t["openapi_file"]))
        # The platform calls the contract's own servers URL, so the deployed URL goes there.
        contract["servers"] = [{"url": url}]
        schema = yaml.safe_dump(contract, sort_keys=False)
        out.append(
            ToolsetSpec(
                id=_check_id(t["id"], "Toolset"),
                display_name=t["display_name"],
                description=t.get("description", "").strip(),
                open_api_schema=schema,
                url=url,
                auth=t.get("auth", "service_agent_id_token"),
            )
        )
    return out


def _operation_ids(schema: str) -> set[str]:
    paths = yaml.safe_load(schema).get("paths", {})
    return {op["operationId"] for ops in paths.values() for op in ops.values() if "operationId" in op}


def load_app(agent_dir: Path = AGENT_DIR, require_urls: bool = False) -> AppSpec:
    """Read agent/app.yaml and every file it references, and validate them.

    require_urls=True (used by the deploy script) refuses to deploy a toolset whose
    URL environment variable is unset; tests leave it False.
    """
    raw = yaml.safe_load((agent_dir / "app.yaml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("app.yaml must be a mapping")

    toolsets = _toolsets(agent_dir, raw.get("toolsets", []), require_urls)
    remote_agents = [
        RemoteAgentSpec(
            id=_check_id(r["id"], "Remote agent"),
            name=r["name"],
            description=r["description"].strip(),
            url=_url(r["url"], require_urls),
            skills=list(r.get("skills", [])),
        )
        for r in raw.get("remote_agents", [])
    ]
    remote_ids = {r.id for r in remote_agents}
    operations = {t.id: _operation_ids(t.open_api_schema) for t in toolsets}
    agents = []
    for a in raw.get("agents", []):
        system_tools = list(a.get("system_tools", []))
        if unknown := set(system_tools) - _SYSTEM_TOOLS:
            raise ConfigError(f"Unknown system tools {sorted(unknown)}")
        refs = []
        for ref in a.get("toolsets", []):
            if ref["toolset"] not in operations:
                raise ConfigError(f"Agent {a['id']} uses unknown toolset {ref['toolset']!r}")
            if missing := set(ref["tools"]) - operations[ref["toolset"]]:
                raise ConfigError(f"Agent {a['id']} is granted operations the contract lacks: {sorted(missing)}")
            refs.append(AgentToolsetRef(ref["toolset"], list(ref["tools"])))
        remotes = list(a.get("remote_agents", []))
        if unknown_remote := set(remotes) - remote_ids:
            raise ConfigError(f"Agent {a['id']} delegates to unknown remote agents {sorted(unknown_remote)}")
        agents.append(
            AgentSpec(
                id=_check_id(a["id"], "Agent"),
                display_name=a["display_name"],
                description=a.get("description", ""),
                instruction=_read_text(agent_dir, a["instruction_file"]),
                system_tools=system_tools,
                toolsets=refs,
                remote_agents=remotes,
            )
        )
    variables = []
    for v in raw.get("variables", []):
        if v["type"] not in _VARIABLE_TYPES:
            raise ConfigError(f"Variable type {v['type']!r} must be one of {sorted(_VARIABLE_TYPES)}")
        variables.append(VariableSpec(v["name"], v.get("description", ""), v["type"], dict(v.get("properties", {}))))
    guardrails = []
    for g in raw.get("guardrails", []):
        kind = g.get("kind", "llm_policy")
        if kind not in {"llm_policy", "regex", "prompt_security"}:
            raise ConfigError(f"Guardrail kind {kind!r} is unknown")
        if g["scope"] not in _SCOPES:
            raise ConfigError(f"Guardrail scope {g['scope']!r} must be one of {sorted(_SCOPES)}")
        patterns = [str(p) for p in g.get("patterns", [])]
        for pattern in patterns:
            re.compile(pattern)  # a bad pattern fails here, not on a live call
        guardrails.append(
            GuardrailSpec(
                id=_check_id(g["id"], "Guardrail"),
                display_name=g["display_name"],
                description=g.get("description", "").strip(),
                scope=g["scope"],
                fail_open=bool(g.get("fail_open", False)),
                prompt=_read_text(agent_dir, g["prompt_file"]) if "prompt_file" in g else "",
                response=g["response"].strip(),
                kind=kind,
                patterns=patterns,
            )
        )
    deployments = []
    for d in raw.get("deployments", []):
        if d["channel_type"] not in _CHANNELS:
            raise ConfigError(f"Channel {d['channel_type']!r} must be one of {sorted(_CHANNELS)}")
        deployments.append(DeploymentSpec(_check_id(d["id"], "Deployment"), d["display_name"], d["channel_type"]))

    redaction = None
    if r := raw.get("redaction"):
        redaction = RedactionSpec(
            inspect_template=_env(r["inspect_template"], require_urls),
            deidentify_template=_env(r["deidentify_template"], require_urls),
        )
    spec = AppSpec(
        app_id=_check_id(raw["app_id"], "App"),
        display_name=raw["display_name"],
        description=raw.get("description", "").strip(),
        location=raw["location"],
        language_code=raw["language_code"],
        time_zone=raw["time_zone"],
        model=raw["model"],
        root_agent=raw["root_agent"],
        agents=agents,
        variables=variables,
        toolsets=toolsets,
        remote_agents=remote_agents,
        redaction=redaction,
        guardrails=guardrails,
        deployments=deployments,
    )
    if spec.root_agent not in {a.id for a in agents}:
        raise ConfigError(f"root_agent {spec.root_agent!r} is not one of the agents")
    return spec

"""Create or update the CX Agent Studio app from the files in agent/.

Every call goes through the official client, google-cloud-ces, against
ces.googleapis.com. The functions are idempotent: run them twice and the
second run updates what exists instead of failing on it.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google.api_core import exceptions
from google.api_core.client_options import ClientOptions
from google.cloud import ces_v1
from google.cloud.ces_v1 import types
from google.protobuf import field_mask_pb2

from brightwater.config import (
    AgentSpec,
    AppSpec,
    DeploymentSpec,
    GuardrailSpec,
    RemoteAgentSpec,
    ToolsetSpec,
    VariableSpec,
)

log = logging.getLogger(__name__)


# ----- Pure builders: spec in, protobuf message out. Unit tested without a network.


def app_name(project: str, spec: AppSpec) -> str:
    return f"projects/{project}/locations/{spec.location}/apps/{spec.app_id}"


def build_variable(spec: VariableSpec) -> types.App.VariableDeclaration:
    schema_type = types.Schema.Type
    schema = types.Schema(type_=getattr(schema_type, spec.type), description=spec.description)
    for prop, prop_type in spec.properties.items():
        schema.properties[prop] = types.Schema(type_=getattr(schema_type, prop_type))
    return types.App.VariableDeclaration(name=spec.name, description=spec.description, schema=schema)


def build_app(spec: AppSpec) -> types.App:
    app = types.App(
        display_name=spec.display_name,
        description=spec.description,
        language_settings=types.LanguageSettings(default_language_code=spec.language_code),
        time_zone_settings=types.TimeZoneSettings(time_zone=spec.time_zone),
        model_settings=types.ModelSettings(model=spec.model),
        variable_declarations=[build_variable(v) for v in spec.variables],
    )
    if spec.redaction and spec.redaction.inspect_template:
        # Cloud DLP redacts transcripts, logs and BigQuery exports before anyone reads them.
        app.logging_settings = types.LoggingSettings(
            redaction_config=types.RedactionConfig(
                enable_redaction=True,
                inspect_template=spec.redaction.inspect_template,
                deidentify_template=spec.redaction.deidentify_template,
            )
        )
    return app


def build_toolset(spec: ToolsetSpec) -> types.Toolset:
    auth = None
    if spec.auth == "service_agent_id_token":
        # CX Agent Studio's service agent signs an ID token; Cloud Run checks it has run.invoker.
        auth = types.ApiAuthentication(service_agent_id_token_auth_config=types.ServiceAgentIdTokenAuthConfig())
    return types.Toolset(
        display_name=spec.display_name,
        description=spec.description,
        open_api_toolset=types.OpenApiToolset(
            open_api_schema=spec.open_api_schema, url=spec.url, api_authentication=auth
        ),
    )


def build_remote_agent_tool(spec: RemoteAgentSpec) -> types.Tool:
    """An A2A tool: the remote agent's card, with the HTTP+JSON interface CX Agent Studio calls."""
    card = types.AgentCard(
        name=spec.name,
        description=spec.description,
        version="1.0.0",
        supported_interfaces=[types.AgentInterface(url=spec.url, protocol_binding="HTTP+JSON", protocol_version="1.0")],
        skills=[
            types.AgentSkill(
                id=str(s["id"]),
                name=str(s["name"]),
                description=str(s["description"]),
                tags=[str(t) for t in s.get("tags", [])],  # type: ignore[attr-defined]
                examples=[str(e) for e in s.get("examples", [])],  # type: ignore[attr-defined]
            )
            for s in spec.skills
        ],
    )
    return types.Tool(
        display_name=spec.name,
        remote_agent_tool=types.RemoteAgentTool(name=spec.name, description=spec.description, agent_card=card),
    )


def build_agent(spec: AgentSpec, app: str = "") -> types.Agent:
    """The agent and its written authority grant: the system tools and toolset operations it may call."""
    return types.Agent(
        display_name=spec.display_name,
        description=spec.description,
        instruction=spec.instruction,
        llm_agent=types.Agent.LlmAgent(),
        tools=[f"{app}/tools/{name}" for name in [*spec.system_tools, *spec.remote_agents]],
        toolsets=[
            types.Agent.AgentToolset(toolset=f"{app}/toolsets/{ref.toolset}", tool_ids=ref.tools)
            for ref in spec.toolsets
        ],
    )


def build_guardrail(spec: GuardrailSpec, model: str) -> types.Guardrail:
    action = types.TriggerAction(
        respond_immediately=types.TriggerAction.RespondImmediately(
            responses=[types.TriggerAction.Response(text=spec.response)]
        )
    )
    guardrail = types.Guardrail(
        display_name=spec.display_name, description=spec.description, enabled=True, action=action
    )
    if spec.kind == "regex":
        # Deterministic, no model call: patterns are checked in both directions as configured.
        content = types.Guardrail.ContentFilter(match_type=types.Guardrail.ContentFilter.MatchType.REGEXP_MATCH)
        if spec.scope in ("USER_QUERY", "USER_QUERY_AND_AGENT_RESPONSE"):
            content.banned_contents_in_user_input.extend(spec.patterns)
        if spec.scope in ("AGENT_RESPONSE", "USER_QUERY_AND_AGENT_RESPONSE"):
            content.banned_contents_in_agent_response.extend(spec.patterns)
        guardrail.content_filter = content
    elif spec.kind == "prompt_security":
        guardrail.llm_prompt_security = types.Guardrail.LlmPromptSecurity(
            default_settings=types.Guardrail.LlmPromptSecurity.DefaultSecuritySettings(), fail_open=spec.fail_open
        )
    else:
        guardrail.llm_policy = types.Guardrail.LlmPolicy(
            prompt=spec.prompt,
            model_settings=types.ModelSettings(model=model),
            policy_scope=getattr(types.Guardrail.LlmPolicy.PolicyScope, spec.scope),
            fail_open=spec.fail_open,
        )
    return guardrail


def build_deployment(spec: DeploymentSpec, app_version: str) -> types.Deployment:
    return types.Deployment(
        display_name=spec.display_name,
        app_version=app_version,
        channel_profile=types.ChannelProfile(
            channel_type=getattr(types.ChannelProfile.ChannelType, spec.channel_type),
        ),
    )


# ----- Network calls.


@dataclass
class DeployResult:
    app: str
    agents: list[str]
    guardrails: list[str]
    app_version: str
    deployments: list[str]


def make_client(project: str) -> ces_v1.AgentServiceClient:
    """Bill API quota to the series project, not to whatever project gcloud last used."""
    return ces_v1.AgentServiceClient(client_options=ClientOptions(quota_project_id=project))


def _done(result: Any) -> Any:
    """Long-running calls return an Operation; wait for it. Others return the resource."""
    return result.result(timeout=300) if hasattr(result, "result") and callable(result.result) else result


def _mask(message: Any, skip: set[str]) -> field_mask_pb2.FieldMask:
    """Update only the fields our spec sets, never output-only ones."""
    pb = type(message).pb(message)
    paths = [f.name for f, _ in pb.ListFields() if f.name not in skip]
    return field_mask_pb2.FieldMask(paths=paths)


def upsert_app(client: ces_v1.AgentServiceClient, project: str, spec: AppSpec) -> str:
    name = app_name(project, spec)
    wanted = build_app(spec)
    try:
        client.get_app(name=name)
    except exceptions.NotFound:
        log.info("Creating app %s", name)
        parent = name.rsplit("/apps/", 1)[0]
        _done(client.create_app(parent=parent, app=wanted, app_id=spec.app_id))
        return name
    wanted.name = name
    client.update_app(app=wanted, update_mask=_mask(wanted, {"name"}))
    log.info("Updated app %s", name)
    return name


def upsert_toolset(client: ces_v1.AgentServiceClient, app: str, spec: ToolsetSpec) -> str:
    name = f"{app}/toolsets/{spec.id}"
    wanted = build_toolset(spec)
    try:
        client.get_toolset(name=name)
    except exceptions.NotFound:
        log.info("Creating toolset %s", name)
        _done(client.create_toolset(parent=app, toolset=wanted, toolset_id=spec.id))
        return name
    wanted.name = name
    client.update_toolset(toolset=wanted, update_mask=_mask(wanted, {"name"}))
    log.info("Updated toolset %s", name)
    return name


def upsert_remote_agent_tool(client: ces_v1.AgentServiceClient, app: str, spec: RemoteAgentSpec) -> str:
    name = f"{app}/tools/{spec.id}"
    wanted = build_remote_agent_tool(spec)
    try:
        client.get_tool(name=name)
    except exceptions.NotFound:
        log.info("Creating A2A tool %s", name)
        _done(client.create_tool(parent=app, tool=wanted, tool_id=spec.id))
        return name
    wanted.name = name
    client.update_tool(tool=wanted, update_mask=_mask(wanted, {"name"}))
    log.info("Updated A2A tool %s", name)
    return name


def set_remote_agent_auth(project: str, tool_name: str) -> None:
    """Make CX Agent Studio call the remote agent with its service agent's ID token.

    The REST API (revision 20260925) has RemoteAgentTool.apiAuthentication, but the
    Python client google-cloud-ces 0.7.2 predates it, so this one field is set over
    REST. Without it, the platform sends a token Cloud Run rejects with 401.
    """
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(creds)
    response = session.patch(
        f"https://ces.googleapis.com/v1/{tool_name}",
        params={"updateMask": "remoteAgentTool.apiAuthentication"},
        headers={"x-goog-user-project": project},
        json={"remoteAgentTool": {"apiAuthentication": {"serviceAgentIdTokenAuthConfig": {}}}},
        timeout=60,
    )
    response.raise_for_status()
    log.info("Set service agent ID token auth on %s", tool_name)


def upsert_agent(client: ces_v1.AgentServiceClient, app: str, spec: AgentSpec) -> str:
    name = f"{app}/agents/{spec.id}"
    wanted = build_agent(spec, app)
    try:
        client.get_agent(name=name)
    except exceptions.NotFound:
        log.info("Creating agent %s", name)
        _done(client.create_agent(parent=app, agent=wanted, agent_id=spec.id))
        return name
    wanted.name = name
    mask = _mask(wanted, {"name", "llm_agent"})
    for path in ("tools", "toolsets"):  # always sent, so revoking a grant in app.yaml revokes it in the app
        if path not in mask.paths:
            mask.paths.append(path)
    client.update_agent(agent=wanted, update_mask=mask)
    log.info("Updated agent %s", name)
    return name


def upsert_guardrail(client: ces_v1.AgentServiceClient, app: str, spec: GuardrailSpec, model: str) -> str:
    name = f"{app}/guardrails/{spec.id}"
    wanted = build_guardrail(spec, model)
    try:
        client.get_guardrail(name=name)
    except exceptions.NotFound:
        log.info("Creating guardrail %s", name)
        _done(client.create_guardrail(parent=app, guardrail=wanted, guardrail_id=spec.id))
        return name
    wanted.name = name
    client.update_guardrail(guardrail=wanted, update_mask=_mask(wanted, {"name"}))
    log.info("Updated guardrail %s", name)
    return name


def link_root_and_guardrails(
    client: ces_v1.AgentServiceClient, app: str, root_agent: str, guardrails: list[str]
) -> None:
    """Point the app at its root agent and its guardrails once both exist."""
    patch = types.App(name=app, root_agent=root_agent, guardrails=guardrails)
    client.update_app(app=patch, update_mask=field_mask_pb2.FieldMask(paths=["root_agent", "guardrails"]))


def snapshot_version(client: ces_v1.AgentServiceClient, app: str, label: str) -> str:
    """Freeze what was just deployed, so a deployment serves a known version."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    version_id = f"{label}-{stamp}"
    version = _done(
        client.create_app_version(
            parent=app,
            app_version=types.AppVersion(display_name=version_id, description=f"Deployed from agent/ ({label})"),
            app_version_id=version_id,
        )
    )
    return str(version.name)


def upsert_deployment(client: ces_v1.AgentServiceClient, app: str, spec: DeploymentSpec, app_version: str) -> str:
    name = f"{app}/deployments/{spec.id}"
    wanted = build_deployment(spec, app_version)
    try:
        client.get_deployment(name=name)
    except exceptions.NotFound:
        log.info("Creating deployment %s", name)
        _done(client.create_deployment(parent=app, deployment=wanted, deployment_id=spec.id))
        return name
    wanted.name = name
    client.update_deployment(deployment=wanted, update_mask=field_mask_pb2.FieldMask(paths=["app_version"]))
    log.info("Pointed deployment %s at %s", name, app_version)
    return name


def deploy(project: str, spec: AppSpec, label: str = "release") -> DeployResult:
    """Create or update everything in agent/app.yaml, in dependency order."""
    client = make_client(project)
    app = upsert_app(client, project, spec)
    for t in spec.toolsets:
        upsert_toolset(client, app, t)
    for r in spec.remote_agents:
        set_remote_agent_auth(project, upsert_remote_agent_tool(client, app, r))
    agents = [upsert_agent(client, app, a) for a in spec.agents]
    guardrails = [upsert_guardrail(client, app, g, spec.model) for g in spec.guardrails]
    link_root_and_guardrails(client, app, f"{app}/agents/{spec.root_agent}", guardrails)
    version = snapshot_version(client, app, label)
    deployments = [upsert_deployment(client, app, d, version) for d in spec.deployments]
    return DeployResult(app, agents, guardrails, version, deployments)

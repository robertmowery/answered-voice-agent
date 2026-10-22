"""Unit tests: the agent files load, validate, and build the right API messages.

None of these tests touch Google Cloud.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.cloud.ces_v1 import types

from brightwater.config import ConfigError, load_app
from brightwater.deploy import build_agent, build_app, build_deployment, build_guardrail
from brightwater.smoke import Case, load_cases, score

ROOT = Path(__file__).resolve().parent.parent


def test_app_yaml_loads_and_points_at_a_real_root_agent() -> None:
    spec = load_app()
    assert spec.root_agent in {a.id for a in spec.agents}
    assert spec.model, "the model must be pinned in agent/app.yaml"


def test_instruction_keeps_the_written_authority_lines() -> None:
    instruction = load_app().agents[0].instruction
    for line in ("Never promise an arrival time other than a window", "Never take payment details", "Gas smell"):
        assert line in instruction


def test_ids_fit_the_api_rule() -> None:
    spec = load_app()
    ids = [
        spec.app_id,
        *(a.id for a in spec.agents),
        *(g.id for g in spec.guardrails),
        *(d.id for d in spec.deployments),
    ]
    assert all(5 <= len(i) <= 36 for i in ids)


def test_short_id_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "a.md").write_text("hello")
    (tmp_path / "app.yaml").write_text(
        "app_id: bw\ndisplay_name: x\nlocation: us\nlanguage_code: en-US\ntime_zone: UTC\n"
        "model: m\nroot_agent: front-desk\n"
        "agents: [{id: front-desk, display_name: x, instruction_file: instructions/a.md}]\n"
    )
    with pytest.raises(ConfigError):
        load_app(tmp_path)


def test_builders_produce_the_expected_messages() -> None:
    spec = load_app()
    app = build_app(spec)
    assert app.model_settings.model == spec.model
    assert app.time_zone_settings.time_zone == "America/New_York"
    agent = build_agent(spec.agents[0])
    assert "llm_agent" in agent
    by_id = {g.id: g for g in spec.guardrails}
    policy = build_guardrail(by_id["no-promises"], spec.model)
    assert policy.llm_policy.policy_scope == types.Guardrail.LlmPolicy.PolicyScope.AGENT_RESPONSE
    assert policy.action.respond_immediately.responses[0].text.startswith("I can't promise")
    cards = build_guardrail(by_id["no-card-numbers"], spec.model)
    assert cards.content_filter.match_type == types.Guardrail.ContentFilter.MatchType.REGEXP_MATCH
    assert list(cards.content_filter.banned_contents_in_user_input) == by_id["no-card-numbers"].patterns
    assert "llm_policy" not in cards
    guard = build_guardrail(by_id["prompt-guard"], spec.model)
    assert "default_settings" in guard.llm_prompt_security
    deployment = build_deployment(spec.deployments[0], "projects/p/locations/us/apps/a/versions/v")
    assert deployment.channel_profile.channel_type == types.ChannelProfile.ChannelType.API


def test_smoke_cases_load() -> None:
    cases = load_cases(ROOT / "evals" / "part1_smoke.yaml")
    assert len(cases) == 8
    assert len({c.id for c in cases}) == 8


def test_score_requires_one_word_from_each_group_and_blocks_patterns() -> None:
    case = Case(id="x", say="?", must_include_any=[["leave", "outside"], ["911"]], must_not_match=[r"\$\s?\d"])
    assert score(case, "Leave now and call 911.") == []
    assert score(case, "Call 911.") == ["missing any of ['leave', 'outside']"]
    assert score(case, "Leave and call 911, it costs $40.") == [r"matched forbidden pattern '\\$\\s?\\d'"]


def test_agent_is_granted_only_listed_operations() -> None:
    spec = load_app()
    agent = build_agent(spec.agents[0], "projects/p/locations/us/apps/a")
    assert list(agent.tools) == [
        "projects/p/locations/us/apps/a/tools/end_session",
        "projects/p/locations/us/apps/a/tools/commerce-agent",
    ]
    granted = [list(t.tool_ids) for t in agent.toolsets]
    assert granted == [
        [
            "getHoursStatus",
            "createTicket",
            "getPriceList",
            "findAppointmentSlots",
            "bookAppointment",
            "sendFollowUpEmail",
            "sendPaymentLink",
            "prepareHandoff",
        ]
    ]


def test_granting_an_operation_the_contract_lacks_fails(tmp_path: Path) -> None:
    import shutil

    shutil.copytree(ROOT / "agent", tmp_path / "agent")
    app_yaml = tmp_path / "agent" / "app.yaml"
    app_yaml.write_text(
        app_yaml.read_text().replace(
            "[getHoursStatus, createTicket, getPriceList", "[getHoursStatus, refundCard, getPriceList"
        )
    )
    with pytest.raises(ConfigError, match="refundCard"):
        load_app(tmp_path / "agent")


def test_deploy_refuses_an_unset_tools_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOOLS_API_URL", raising=False)
    with pytest.raises(ConfigError, match="TOOLS_API_URL"):
        load_app(require_urls=True)


def test_transfer_variable_is_an_object_with_a_phone_number() -> None:
    from brightwater.deploy import build_variable

    spec = {v.name: v for v in load_app().variables}["telephonyTransferCall"]
    decl = build_variable(spec)
    assert decl.schema.type_ == types.Schema.Type.OBJECT
    assert "phoneNumber" in decl.schema.properties


def test_contract_has_no_stray_keys() -> None:
    """A comma inside an unquoted YAML flow mapping silently becomes a new key; the API rejects it."""
    import yaml

    allowed = {"type", "description", "enum", "nullable", "items", "properties", "required", "format"}
    contract = yaml.safe_load((ROOT / "agent" / "tools" / "brightwater_api.yaml").read_text())

    def check(schema: dict) -> None:
        assert set(schema) <= allowed, f"unexpected schema keys {set(schema) - allowed}"
        for child in schema.get("properties", {}).values():
            check(child)
        if "items" in schema:
            check(schema["items"])

    for ops in contract["paths"].values():
        for op in ops.values():
            for response in op.get("responses", {}).values():
                for media in response.get("content", {}).values():
                    check(media["schema"])
            for media in op.get("requestBody", {}).get("content", {}).values():
                check(media["schema"])


def test_contract_servers_url_is_the_deployed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    monkeypatch.setenv("TOOLS_API_URL", "https://tools-api-123.us-central1.run.app")
    monkeypatch.setenv("COMMERCE_AGENT_URL", "https://commerce-agent-123.us-central1.run.app")
    monkeypatch.setenv("DLP_INSPECT_TEMPLATE", "projects/p/locations/global/inspectTemplates/i")
    monkeypatch.setenv("DLP_DEIDENTIFY_TEMPLATE", "projects/p/locations/global/deidentifyTemplates/d")
    toolset = load_app(require_urls=True).toolsets[0]
    assert yaml.safe_load(toolset.open_api_schema)["servers"] == [{"url": "https://tools-api-123.us-central1.run.app"}]


def test_commerce_agent_card_points_at_the_a2a_rest_base(monkeypatch: pytest.MonkeyPatch) -> None:
    from brightwater.deploy import build_remote_agent_tool

    monkeypatch.setenv("TOOLS_API_URL", "https://tools-api-123.us-central1.run.app")
    monkeypatch.setenv("COMMERCE_AGENT_URL", "https://commerce-agent-123.us-central1.run.app")
    monkeypatch.setenv("DLP_INSPECT_TEMPLATE", "projects/p/locations/global/inspectTemplates/i")
    monkeypatch.setenv("DLP_DEIDENTIFY_TEMPLATE", "projects/p/locations/global/deidentifyTemplates/d")
    remote = load_app(require_urls=True).remote_agents[0]
    tool = build_remote_agent_tool(remote)
    interface = tool.remote_agent_tool.agent_card.supported_interfaces[0]
    assert interface.url == "https://commerce-agent-123.us-central1.run.app/v1"
    assert interface.protocol_binding == "HTTP+JSON"


def test_card_pattern_catches_spoken_and_typed_card_numbers() -> None:
    import re

    pattern = re.compile({g.id: g for g in load_app().guardrails}["no-card-numbers"].patterns[0])
    for said in ("4111 1111 1111 1111", "4111-1111-1111-1111", "my card is 4111111111111111 thanks"):
        assert pattern.search(said), said
    for fine in ("call me at 202-555-0147", "ZIP 20016", "ticket BW-20261015-9C4EF2", "invoice 4471"):
        assert not pattern.search(fine), fine


def test_every_granted_operation_is_in_the_written_authority_file() -> None:
    import yaml

    authority = yaml.safe_load((ROOT / "agent" / "authority.yaml").read_text())["actors"]["front-desk"]
    written = set(authority["observe"]) | set(authority["change"]) | set(authority["escalate"])
    agent = load_app().agents[0]
    granted = {op for ref in agent.toolsets for op in ref.tools} | set(agent.system_tools) | set(agent.remote_agents)
    assert granted <= written, f"granted in app.yaml but not written down: {granted - written}"
    assert "getHandoff" not in granted, "the call desk's screen pop must not be readable by the agent"


def test_commerce_limits_match_the_store() -> None:
    import yaml

    written = yaml.safe_load((ROOT / "agent" / "authority.yaml").read_text())["actors"]["commerce-agent"]["limits"]
    store = yaml.safe_load((ROOT / "services" / "ucp-server" / "policy" / "catalog.yaml").read_text())["limits"]
    assert written["max_quantity_per_item"] == store["max_quantity_per_item"]
    assert written["max_order_total_cents"] == store["max_order_total"]


def test_cloud_roles_match_terraform() -> None:
    import re

    import yaml

    written = yaml.safe_load((ROOT / "agent" / "authority.yaml").read_text())["cloud_identities"]
    tf = "\n".join(p.read_text() for p in (ROOT / "infra" / "terraform").glob("*.tf"))
    granted: dict[str, set[str]] = {}
    for block in re.findall(
        r'resource "google_(?:project|service_account|pubsub_topic)_iam_member"[^{]*\{(.*?)\n\}', tf, re.S
    ):
        role = re.search(r'role\s*=\s*"([^"]+)"', block)
        member = re.search(r"google_service_account\.(\w+)\.email", block)
        if role and member:
            granted.setdefault(member.group(1).replace("_", "-"), set()).add(role.group(1))
    for identity, spec in written.items():
        assert granted.get(identity, set()) == set(spec["roles"]), identity


def test_handoff_checks_catch_silent_transfers_and_mangled_headers() -> None:
    from brightwater.conversation import Turn, handoff_failures

    def turn(reply: str, headers: object) -> Turn:
        end = {"params": {"liveAgentHandoff": {"sipRefer": True, "xHeaders": headers}}}
        return Turn(say="x", reply=reply, seconds=1.0, tools=[], end_session=end)

    good = {"handoff-id": "HO-1", "queue": "billing"}
    assert handoff_failures([turn("Connecting you now.", good)]) == []
    assert handoff_failures([turn("", good)]) == ["transferred to a person without telling the caller"]
    assert len(handoff_failures([turn("Connecting you.", '{handoff-id: "HO-1"}')])) == 1

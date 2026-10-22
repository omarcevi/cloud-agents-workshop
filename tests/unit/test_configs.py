"""Config and policy files are well formed (no network).

- Gateway YAML validates against the gcloud import schemas (vendored in tests/schemas).
- The egress access policy, endpoint list, monitoring and memory configs have the shape
  the scripts expect.
- Generated files (toolspecs, eval datasets) match their sources.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "tests" / "schemas"
GATEWAY = ROOT / "infra" / "gateway"


def schema_validator(group: str, name: str) -> jsonschema.Draft6Validator:
    """Validator for a gcloud schema whose $refs point at sibling YAML files."""
    def retrieve(uri: str) -> Resource:
        return Resource.from_contents(yaml.safe_load((SCHEMAS / group / uri).read_text()))

    schema = yaml.safe_load((SCHEMAS / group / f"{name}.yaml").read_text())
    return jsonschema.Draft6Validator(schema, registry=Registry(retrieve=retrieve))


def render(text: str) -> str:
    return (
        text.replace("PROJECT_ID", "demo-project")
        .replace("REGION", "europe-west1")
        .replace("GATEWAY", "workplace-gw")
    )


@pytest.mark.parametrize(
    ("file", "group", "schema"),
    [
        ("gateway.yaml", "networkservices", "AgentGateway"),
        ("iap-authz-extension.yaml", "networkservices", "AuthzExtension"),
        ("iap-authz-policy.yaml", "networksecurity", "AuthzPolicy"),
    ],
)
def test_gateway_yaml_matches_gcloud_schema(file: str, group: str, schema: str) -> None:
    document = yaml.safe_load(render((GATEWAY / file).read_text()))
    errors = sorted(schema_validator(group, schema).iter_errors(document), key=str)
    assert not errors, [e.message for e in errors]


def test_gateway_is_egress_mode_for_mcp() -> None:
    gateway = yaml.safe_load(render((GATEWAY / "gateway.yaml").read_text()))
    assert gateway["googleManaged"]["governedAccessPath"] == "AGENT_TO_ANYWHERE"
    assert gateway["protocols"] == ["MCP"]
    assert gateway["registries"] == ["//agentregistry.googleapis.com/projects/demo-project/locations/europe-west1"]


def test_iap_is_the_request_authorizer_and_enforces() -> None:
    extension = yaml.safe_load((GATEWAY / "iap-authz-extension.yaml").read_text())
    assert extension["service"] == "iap.googleapis.com"
    assert extension["metadata"]["iapPolicyVersion"] == "V2"
    assert "iamEnforcementMode" not in extension["metadata"], "DRY_RUN would not block anything"
    policy = yaml.safe_load(render((GATEWAY / "iap-authz-policy.yaml").read_text()))
    assert policy["policyProfile"] == "REQUEST_AUTHZ"
    assert policy["customProvider"]["authzExtension"]["resources"][0].endswith("/authzExtensions/workplace-iap")


# Attributes from the Agent Gateway UAP CEL reference (docs/VERIFIED.md).
CEL_ATTRIBUTES = {
    "destination.is_registered",
    "destination.agent_registry.resource_type",
    "destination.agent_registry.location",
    "destination.agent_registry.project_id",
    "destination.agent_registry.agent.name",
    "destination.agent_registry.mcp_server.name",
    "destination.agent_registry.mcp_server.method",
    "destination.agent_registry.mcp_server.tool.name",
    "destination.agent_registry.mcp_server.tool.annotations.read_only_hint",
    "destination.agent_registry.mcp_server.tool.annotations.destructive_hint",
    "destination.agent_registry.mcp_server.tool.annotations.idempotent_hint",
    "destination.agent_registry.mcp_server.tool.annotations.open_world_hint",
    "destination.agent_registry.endpoint.name",
    "destination.unregistered.host",
    "destination.unregistered.path",
    "destination.unregistered.method",
}


def test_egress_policy_allows_hr_and_it_and_denies_compensation() -> None:
    rules = json.loads((GATEWAY / "egress-policy.rules.json").read_text())
    by_effect: dict[str, list[dict]] = {"ALLOW": [], "DENY": []}
    for rule in rules:
        assert set(rule) == {"description", "effect", "principals", "operation", "conditions"}
        assert rule["operation"] == {"permissions": ["iap.googleapis.com/resources.egressViaIAP"]}
        by_effect[rule["effect"]].append(rule)
    allowed = " ".join(r["conditions"]["iap.googleapis.com"]["expression"] for r in by_effect["ALLOW"])
    denied = " ".join(r["conditions"]["iap.googleapis.com"]["expression"] for r in by_effect["DENY"])
    assert "HRIS_MCP_SERVER" in allowed and "TICKETING_MCP_SERVER" in allowed and "GOOGLE_APIS_ENDPOINT" in allowed
    assert "COMPENSATION_MCP_SERVER" not in allowed
    assert "COMPENSATION_MCP_SERVER" in denied
    assert all(r["principals"] == ["PROJECT_AGENTS"] for r in by_effect["DENY"])


def test_policy_rules_use_known_attributes_one_destination_type_each() -> None:
    for rule in json.loads((GATEWAY / "egress-policy.rules.json").read_text()):
        expression = rule["conditions"]["iap.googleapis.com"]["expression"]
        used = set(re.findall(r"destination(?:\.[a-z_]+)+", expression))
        assert used <= CEL_ATTRIBUTES, used - CEL_ATTRIBUTES
        # Mixing endpoint and MCP server attributes in one rule never matched in testing.
        assert not ({a for a in used if ".endpoint." in a} and {a for a in used if ".mcp_server." in a})


def test_platform_endpoints_cover_what_the_agent_calls() -> None:
    lines = [
        line.strip()
        for line in (GATEWAY / "platform-endpoints.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert all(line.startswith("https://") and line.count("/") == 2 for line in lines)
    hosts = {line.removeprefix("https://") for line in lines}
    for required in (
        "aiplatform.mtls.googleapis.com",            # Gemini (MODEL_LOCATION=global)
        "REGION-aiplatform.googleapis.com",           # Sessions, Memory Bank
        "REGION-aiplatform.mtls.googleapis.com",
        "telemetry.googleapis.com",                   # traces, logs
        "telemetry.mtls.googleapis.com",
        "cloudresourcemanager.mtls.googleapis.com",
        "iamcredentials.mtls.googleapis.com",
    ):
        assert required in hosts, required
    assert len(lines) <= 50  # interfaces per registry service


def test_toolspecs_match_the_servers() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("export_toolspecs", ROOT / "scripts" / "export_toolspecs.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    for name, server in module.SERVERS.items():
        expected = asyncio.run(module.toolspec(server))
        actual = json.loads((GATEWAY / "toolspecs" / f"{name}.json").read_text())
        assert actual == expected, f"run: uv run python scripts/export_toolspecs.py ({name})"
        assert len((GATEWAY / "toolspecs" / f"{name}.json").read_bytes()) < 10_000


def test_log_metric_and_dashboard_agree() -> None:
    metrics = {p.stem: json.loads(p.read_text()) for p in (ROOT / "infra" / "monitoring" / "log-metrics").glob("*.json")}
    for name, metric in metrics.items():
        assert metric["name"] == name
        for key, extractor in metric.get("labelExtractors", {}).items():
            assert key in {label["key"] for label in metric["metricDescriptor"]["labels"]}
            assert extractor.startswith("EXTRACT(")
    blocked = metrics["workplace_tool_blocked"]
    assert 'labels."event.name"="workplace.tool_blocked"' in blocked["filter"]
    from app.audit import EVENT_NAME

    assert EVENT_NAME == "workplace.tool_blocked"
    dashboard = json.loads((ROOT / "infra" / "monitoring" / "dashboard.json").read_text())
    tiles = dashboard["mosaicLayout"]["tiles"]
    titles = " | ".join(t["widget"]["title"] for t in tiles)
    for needle in ("Requests per minute", "p50 / p95", "Tool error rate", "blocked", "Gateway"):
        assert needle.lower() in titles.lower(), needle
    referenced = set(re.findall(r"logging\.googleapis\.com/user/([a-z_]+)", json.dumps(dashboard)))
    assert referenced <= set(metrics), referenced - set(metrics)
    assert "REASONING_ENGINE_ID" in json.dumps(dashboard)


def test_memory_bank_config() -> None:
    config = json.loads((ROOT / "infra" / "memory" / "memory-bank.json").read_text())
    topics = config["customization_configs"][0]["memory_topics"]
    labels = {t.get("custom_memory_topic", {}).get("label") for t in topics}
    assert {"team_and_office", "work_preferences"} <= labels
    assert config["generation_config"]["model"].startswith("projects/PROJECT_ID/locations/")


def test_eval_datasets_are_up_to_date() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_datasets", ROOT / "evals" / "build_datasets.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    for name, dataset in module.build().items():
        on_disk = json.loads((ROOT / "evals" / "datasets" / f"{name}.json").read_text())
        assert on_disk == dataset, f"run: uv run python evals/build_datasets.py ({name})"


def test_thresholds_cover_the_configured_metrics() -> None:
    thresholds = yaml.safe_load((ROOT / "evals" / "thresholds.yaml").read_text())
    for suite, config_file in (("behaviour", "eval_config.yaml"), ("handbook", "eval_config.handbook.yaml")):
        config = yaml.safe_load((ROOT / "evals" / config_file).read_text())
        assert set(config["metrics_to_run"]) == set(thresholds[suite])
        for metric in config.get("custom_metrics", []):
            assert (ROOT / "evals" / metric["custom_function_file"]).exists()

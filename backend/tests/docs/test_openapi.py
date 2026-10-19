from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = ROOT / "docs" / "api" / "openapi.yaml"


def _spec():
    with OPENAPI_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_openapi_yaml_is_valid_and_versioned():
    spec = _spec()

    assert spec["openapi"].startswith("3.")
    assert spec["servers"][0]["url"] == "/api/v1"
    assert "bearerAuth" in spec["components"]["securitySchemes"]


def test_openapi_contains_core_p0_paths():
    paths = _spec()["paths"]

    required = {
        "/auth/login",
        "/kbs",
        "/docs/upload",
        "/ingestions/events",
        "/chunks",
        "/chunks/regenerate",
        "/chats/ask",
        "/messages/cancel",
        "/traces/detail",
        "/evals/runs",
        "/evals/datasets/cases",
        "/model-policy",
        "/providers",
        "/generations/activate",
        "/generations/rollback",
        "/docs/grants",
        "/sources/sync",
        "/admin/model-policy",
    }

    assert required.issubset(paths)


def test_openapi_operations_have_summaries():
    for path, item in _spec()["paths"].items():
        for method, operation in item.items():
            if method in {"get", "post", "patch", "delete"}:
                assert operation.get("summary"), "{0} {1}".format(method, path)


def test_openapi_paths_have_no_path_parameters():
    for path in _spec()["paths"]:
        assert "{" not in path


def test_page_map_has_no_team_route_prefix():
    page_map = (ROOT / "docs" / "product" / "page-map.md").read_text(encoding="utf-8")

    assert "/teams/:teamId/" not in page_map


def test_openapi_mutations_are_post_only():
    for path, item in _spec()["paths"].items():
        for method in item:
            if method != "get":
                assert method == "post", "{0} {1}".format(method, path)


def test_openapi_enums_match_design_separation():
    schemas = _spec()["components"]["schemas"]

    assert schemas["Role"]["enum"] == [
        "admin",
        "leader",
        "member",
        "viewer",
    ]
    assert schemas["Visibility"]["enum"] == ["private", "team_shared"]
    assert "restricted" in schemas["DataClassification"]["enum"]
    assert "cancelled" in schemas["IngestionStatus"]["enum"]


def test_trace_contract_exposes_all_retrieval_stages():
    trace = _spec()["components"]["schemas"]["RetrievalTrace"]["properties"]

    assert {
        "bm25_candidates",
        "dense_candidates",
        "rrf_candidates",
        "rerank_candidates",
        "final_context",
        "model",
        "stage_latency_ms",
        "degraded",
    }.issubset(trace)


def test_list_envelopes_model_array_data():
    schemas = _spec()["components"]["schemas"]

    assert schemas["ListEnvelope"]["properties"]["data"]["type"] == "array"
    assert (
        schemas["TeamListEnvelope"]["allOf"][1]["properties"]["data"]["items"]["$ref"]
        == "#/components/schemas/Team"
    )
    assert (
        schemas["KnowledgeBaseListEnvelope"]["allOf"][1]["properties"]["data"][
            "items"
        ]["$ref"]
        == "#/components/schemas/KnowledgeBase"
    )


def test_team_and_kb_lists_use_list_envelopes():
    paths = _spec()["paths"]

    assert (
        paths["/teams"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/TeamListEnvelope"
    )
    assert (
        paths["/kbs"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/KnowledgeBaseListEnvelope"
    )


def test_team_and_kb_schemas_expose_timestamps():
    schemas = _spec()["components"]["schemas"]

    assert {"created_at", "updated_at"}.issubset(schemas["Team"]["properties"])
    assert {"created_at", "updated_at"}.issubset(
        schemas["KnowledgeBase"]["properties"]
    )


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
        "/teams/{team_id}/knowledge-bases",
        "/teams/{team_id}/knowledge-bases/{kb_id}/documents/upload",
        "/teams/{team_id}/ingestion-runs/{run_id}/events",
        "/teams/{team_id}/chunks/{chunk_id}",
        "/teams/{team_id}/chunks/{chunk_id}/regenerate",
        "/teams/{team_id}/conversations/{conversation_id}/ask",
        "/teams/{team_id}/conversations/{conversation_id}/messages/{message_id}/cancel",
        "/teams/{team_id}/traces/{trace_id}",
        "/teams/{team_id}/evaluation-runs",
        "/teams/{team_id}/evaluation-datasets/{dataset_id}/cases",
        "/teams/{team_id}/model-policy",
        "/teams/{team_id}/model-providers",
        "/teams/{team_id}/index-generations/{generation_id}/activate",
        "/teams/{team_id}/index-generations/{generation_id}/rollback",
        "/teams/{team_id}/documents/{document_id}/grants",
        "/teams/{team_id}/sources/{source_id}/sync",
        "/admin/deployment-model-policy",
    }

    assert required.issubset(paths)


def test_openapi_operations_have_summaries():
    for path, item in _spec()["paths"].items():
        for method, operation in item.items():
            if method in {"get", "post", "patch", "delete"}:
                assert operation.get("summary"), "{0} {1}".format(method, path)


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


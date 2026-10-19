import ast
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = ROOT / "docs" / "api" / "openapi.yaml"
API_CONTRACT_PATH = ROOT / "docs" / "api" / "api-contract.md"


def _spec():
    with OPENAPI_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _operations(spec):
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method in {"get", "post"}:
                yield path, method, operation


def _component_name(reference):
    return reference.rsplit("/", 1)[-1]


def _backend_paged_get_paths():
    paged_paths = set()
    api_dir = ROOT / "backend" / "app" / "api" / "v1"
    for path in api_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arguments = {argument.arg for argument in node.args.args}
            if not {"limit", "cursor"}.issubset(arguments):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not isinstance(decorator.func, ast.Attribute):
                    continue
                if decorator.func.attr == "get" and decorator.args:
                    paged_paths.add(ast.literal_eval(decorator.args[0]))
    return paged_paths


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
        "/kbs/members",
        "/kbs/members/update",
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
        "/providers/models",
        "/generations/activate",
        "/generations/rollback",
        "/docs/grants",
        "/sources/sync",
        "/admin/model-policy",
        "/admin/providers/models",
    }

    assert required.issubset(paths)


def test_evaluation_stream_event_declares_cancelled_and_contract_documents_it():
    spec = _spec()
    event_enum = spec["components"]["schemas"]["EvaluationStreamEvent"]["properties"][
        "event"
    ]["enum"]
    contract = API_CONTRACT_PATH.read_text(encoding="utf-8")
    evaluation_contract = contract.split("## 11. 评测", 1)[1].split("## 12.", 1)[0]

    assert "cancelled" in event_enum
    assert "event: cancelled" in evaluation_contract
    assert "`cancelled` 是终止事件" in evaluation_contract


def test_document_upload_contract_uses_explicit_metadata_fields_without_owner_override():
    spec = _spec()
    schema = spec["components"]["schemas"]["DocumentUploadBody"]
    contract = API_CONTRACT_PATH.read_text(encoding="utf-8")
    upload_contract = contract.split("文件上传：", 1)[1].split("成功返回", 1)[0]

    assert schema["required"] == ["team_id", "kb_id", "file"]
    assert set(schema["properties"]) == {
        "team_id",
        "kb_id",
        "file",
        "product",
        "version_values",
        "visibility",
        "data_classification",
    }
    assert "owner_user_id" not in schema["properties"]
    for field in (
        "team_id",
        "kb_id",
        "file",
        "product",
        "version_values",
        "visibility",
        "data_classification",
    ):
        assert "`{0}`".format(field) in upload_contract
    assert "`owner_user_id`：" not in upload_contract
    assert "`metadata`" not in upload_contract


def test_typed_write_request_schemas_are_closed():
    schemas = _spec()["components"]["schemas"]

    for schema_name in (
        "ChunkUpdateBody",
        "ChunkBulkBody",
        "ProviderCreateBody",
        "AdminProviderCreateBody",
        "AdminProviderUpdateBody",
    ):
        assert schemas[schema_name].get("additionalProperties") is False, schema_name


def test_openapi_matches_admin_managed_onboarding_and_lifecycle_routes():
    spec = _spec()
    paths = spec["paths"]

    assert "/auth/register" not in paths
    assert {
        "/admin/users/update",
        "/admin/audit",
        "/admin/audit/detail",
        "/docs/download",
        "/generations/reindex",
    }.issubset(paths)
    assert "requestBody" not in paths["/auth/refresh"]["post"]
    assert "requestBody" not in paths["/auth/logout"]["post"]


def test_admin_user_update_contract_matches_typed_handler():
    schema = _spec()["components"]["schemas"]["AdminUserUpdateBody"]

    assert schema["required"] == ["user_id"]
    assert set(schema["properties"]) == {"user_id", "status", "team_id", "role"}
    assert schema["properties"]["status"]["$ref"].endswith("/UserStatus")
    assert schema["properties"]["role"]["$ref"].endswith("/TeamRole")
    assert schema["anyOf"] == [
        {"required": ["status"]},
        {"required": ["team_id", "role"]},
    ]


def test_team_member_update_status_contract_uses_update_values_only():
    schemas = _spec()["components"]["schemas"]

    update_status = schemas["TeamMemberUpdateBody"]["properties"]["status"]
    assert update_status["$ref"].endswith("/MemberUpdateStatus")
    assert schemas["MemberUpdateStatus"]["enum"] == ["active", "disabled"]
    assert schemas["MemberStatus"]["enum"] == ["active", "disabled", "removed"]


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
    assert schemas["TeamRole"]["enum"] == ["leader", "member", "viewer"]
    assert schemas["Team"]["properties"]["role"]["$ref"].endswith("/TeamRole")
    assert schemas["Visibility"]["enum"] == ["private", "team_shared"]
    assert "restricted" in schemas["DataClassification"]["enum"]
    assert "completed" in schemas["IngestionStatus"]["enum"]
    assert "active" not in schemas["IngestionStatus"]["enum"]
    assert "cancelled" in schemas["IngestionStatus"]["enum"]


def test_trace_contract_exposes_all_retrieval_stages():
    schemas = _spec()["components"]["schemas"]
    trace = schemas["RetrievalTrace"]["properties"]

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
    assert trace["feedback"]["type"] == "array"
    assert (
        trace["feedback"]["items"]["$ref"]
        == "#/components/schemas/TraceFeedback"
    )
    assert "user_id" not in schemas["TraceFeedback"]["properties"]


def test_page_envelopes_model_array_data():
    schemas = _spec()["components"]["schemas"]

    assert schemas["PageEnvelope"]["properties"]["data"]["type"] == "array"
    assert (
        schemas["TeamPageEnvelope"]["allOf"][1]["properties"]["data"]["items"]["$ref"]
        == "#/components/schemas/Team"
    )
    assert (
        schemas["KnowledgeBasePageEnvelope"]["allOf"][1]["properties"]["data"][
            "items"
        ]["$ref"]
        == "#/components/schemas/KnowledgeBase"
    )
    assert (
        schemas["TeamPageEnvelope"]["allOf"][0]["$ref"]
        == "#/components/schemas/PageEnvelope"
    )


def test_team_and_kb_lists_use_page_envelopes():
    paths = _spec()["paths"]

    assert (
        paths["/teams"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/TeamPageEnvelope"
    )
    assert (
        paths["/kbs"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/KnowledgeBasePageEnvelope"
    )


def test_team_and_kb_schemas_expose_timestamps():
    schemas = _spec()["components"]["schemas"]

    assert {"created_at", "updated_at"}.issubset(schemas["Team"]["properties"])
    assert {"created_at", "updated_at"}.issubset(
        schemas["KnowledgeBase"]["properties"]
    )


def test_kb_membership_contract_is_explicit():
    spec = _spec()
    schemas = spec["components"]["schemas"]

    assert (
        spec["paths"]["/kbs/members"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeBaseMemberPageEnvelope"
    )
    assert schemas["KnowledgeBaseMember"]["required"] == [
        "kb_id",
        "user_id",
        "email",
        "display_name",
        "status",
    ]
    assert schemas["KnowledgeBaseMembersUpdateBody"]["required"] == [
        "team_id",
        "kb_id",
        "user_ids",
    ]


def test_openapi_has_no_generic_or_unnamed_request_body():
    spec = _spec()
    schemas = spec["components"]["schemas"]

    assert "GenericBody" not in schemas
    assert "MultipartBody" not in schemas
    assert "GenericBody" not in OPENAPI_PATH.read_text(encoding="utf-8")

    for path, method, operation in _operations(spec):
        request_body = operation.get("requestBody")
        if request_body is None:
            if method == "post":
                assert (method, path) in {
                    ("post", "/auth/refresh"),
                    ("post", "/auth/logout"),
                }
            continue

        assert request_body["required"] is True
        content = request_body["content"]
        assert len(content) == 1
        schema = next(iter(content.values()))["schema"]
        assert "$ref" in schema, "{0} {1}".format(method, path)
        component = _component_name(schema["$ref"])
        assert component in schemas, "{0} {1}".format(method, path)
        assert schemas[component].get("required"), "{0} {1}".format(method, path)


def test_all_operations_use_structured_error_response():
    spec = _spec()
    error_response = spec["components"]["responses"]["ErrorResponse"]

    assert (
        error_response["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorEnvelope"
    )
    for path, method, operation in _operations(spec):
        assert (
            operation["responses"]["default"]["$ref"]
            == "#/components/responses/ErrorResponse"
        ), "{0} {1}".format(method, path)


def test_envelope_data_supports_objects_and_arrays():
    data_schema = _spec()["components"]["schemas"]["Envelope"]["properties"]["data"]

    assert {option["type"] for option in data_schema["oneOf"]} == {"object", "array"}


def test_auth_refresh_logout_have_no_request_body():
    paths = _spec()["paths"]

    assert "requestBody" not in paths["/auth/refresh"]["post"]
    assert "requestBody" not in paths["/auth/logout"]["post"]
    assert paths["/auth/refresh"]["post"]["security"] == []


def test_upload_and_dataset_import_content_types():
    paths = _spec()["paths"]

    upload = paths["/docs/upload"]["post"]
    assert upload["responses"]["202"]
    assert (
        upload["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
        == "#/components/schemas/DocumentUploadBody"
    )
    required = _spec()["components"]["schemas"]["DocumentUploadBody"]["required"]
    assert required == ["team_id", "kb_id", "file"]

    dataset_import = paths["/evals/datasets/import"]["post"]
    assert set(dataset_import["responses"]) == {"201", "default"}
    assert list(dataset_import["requestBody"]["content"]) == ["application/json"]
    assert (
        dataset_import["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/EvaluationDatasetImportBody"
    )


def test_chat_ask_declares_json_and_sse_responses():
    ask = _spec()["paths"]["/chats/ask"]["post"]
    content = ask["responses"]["200"]["content"]

    assert set(content) == {"application/json", "text/event-stream"}
    assert content["application/json"]["schema"]["$ref"].endswith("/Envelope")
    assert (
        content["text/event-stream"]["schema"]["$ref"]
        == "#/components/schemas/AskStreamEvent"
    )


def test_chat_ask_requires_provider_and_model():
    schema = _spec()["components"]["schemas"]["ChatAskBody"]

    assert "provider_id" in schema["required"]
    assert "model_id" in schema["required"]
    assert schema["properties"]["provider_id"]["minLength"] == 1
    assert schema["properties"]["model_id"]["minLength"] == 1


def test_contract_has_no_extractive_fallback():
    contract = API_CONTRACT_PATH.read_text(encoding="utf-8")

    assert "local-" + "extractive" not in contract
    assert "local_" + "extractive_fallback" not in contract
    assert "extractive-" + "local" not in contract


def test_contract_documents_required_selection_and_unavailable_provider_error():
    contract = API_CONTRACT_PATH.read_text(encoding="utf-8")
    ask_contract = contract.split("### 9.1 问答请求", 1)[1].split("### 9.2", 1)[0]

    assert "`provider_id`" in ask_contract
    assert "`model_id`" in ask_contract
    assert "必填且非空" in ask_contract
    assert "422 VALIDATION_FAILED" in ask_contract
    assert "503 MODEL_UNAVAILABLE" in ask_contract


def test_contract_documents_provider_error_semantics():
    contract = API_CONTRACT_PATH.read_text(encoding="utf-8")
    ask_contract = contract.split("### 9.1 问答请求", 1)[1].split("### 9.2", 1)[0]

    assert "404 NOT_FOUND" in ask_contract
    assert "409 RESOURCE_STATE_CONFLICT" in ask_contract
    assert "403 POLICY_DENIED" in ask_contract
    assert "502 MODEL_AUTH_FAILED" in ask_contract
    assert "502 MODEL_RESPONSE_INVALID" in ask_contract
    assert "503 MODEL_UNAVAILABLE" in ask_contract
    assert "凭据缺失或不可解密时返回\n`409 RESOURCE_STATE_CONFLICT`" in ask_contract
    model_unavailable_row = contract.split(
        "| 503 | `MODEL_UNAVAILABLE`", 1
    )[1].split("\n", 1)[0]
    assert "凭据缺失或不可解密" not in model_unavailable_row

    ask_operation = _spec()["paths"]["/chats/ask"]["post"]
    assert "409 RESOURCE_STATE_CONFLICT" in ask_operation["description"]
    assert "503 MODEL_UNAVAILABLE" in ask_operation["description"]


def test_provider_contract_documents_has_api_key():
    schemas = _spec()["components"]["schemas"]
    for schema_name in ("Provider", "AdminProvider"):
        schema = schemas[schema_name]
        assert "has_api_key" in schema["required"]
        assert schema["properties"]["has_api_key"]["type"] == "boolean"
        assert "decryptable" in schema["properties"]["has_api_key"]["description"]

    contract = API_CONTRACT_PATH.read_text(encoding="utf-8")
    provider_contract = contract.split("供应商 `provider_type` 仅允许：", 1)[1]
    assert "`has_api_key`" in provider_contract
    assert "可解密" in provider_contract


def test_page_map_disables_send_until_all_required_selections_exist():
    page_map = (ROOT / "docs" / "product" / "page-map.md").read_text(encoding="utf-8")
    chat_page = page_map.split("### 3.1 问答工作台", 1)[1].split("### 3.2", 1)[0]

    assert "发送按钮" in chat_page
    assert "禁用" in chat_page
    assert "灰色" in chat_page
    assert "供应商、模型、知识库和问题" in chat_page


def test_streaming_events_have_specific_models():
    paths = _spec()["paths"]

    assert (
        paths["/ingestions/events"]["get"]["responses"]["200"]["content"][
            "text/event-stream"
        ]["schema"]["$ref"]
        == "#/components/schemas/IngestionStreamEvent"
    )
    assert (
        paths["/evals/runs/events"]["get"]["responses"]["200"]["content"][
            "text/event-stream"
        ]["schema"]["$ref"]
        == "#/components/schemas/EvaluationStreamEvent"
    )


def test_pagination_parameters_match_backend_handlers():
    spec = _spec()
    schemas = spec["components"]["schemas"]
    paged_paths = {
        "/admin/users": "AdminUserPageEnvelope",
        "/teams": "TeamPageEnvelope",
        "/members": "TeamMemberPageEnvelope",
        "/kbs": "KnowledgeBasePageEnvelope",
        "/kbs/members": "KnowledgeBaseMemberPageEnvelope",
        "/docs": "DocumentPageEnvelope",
        "/docs/versions": "DocumentVersionPageEnvelope",
        "/docs/grants": "DocumentGrantPageEnvelope",
        "/ingestions": "IngestionRunPageEnvelope",
        "/docs/tasks": "DocumentTaskPageEnvelope",
        "/chunks": "ChunkPageEnvelope",
        "/docs/chunks": "DocumentChunkPageEnvelope",
        "/chunks/history": "ChunkHistoryPageEnvelope",
        "/chats": "ChatPageEnvelope",
        "/chats/messages": "MessagePageEnvelope",
        "/traces": "RetrievalTracePageEnvelope",
        "/evals/datasets": "EvaluationDatasetPageEnvelope",
        "/evals/datasets/cases": "EvaluationCasePageEnvelope",
        "/evals/runs": "EvaluationRunPageEnvelope",
        "/sources": "SourceConnectionPageEnvelope",
        "/credentials": "CredentialPageEnvelope",
        "/providers": "ProviderPageEnvelope",
        "/model-calls": "ModelCallPageEnvelope",
        "/audit": "AuditLogPageEnvelope",
        "/admin/audit": "AuditLogPageEnvelope",
        "/admin/providers": "AdminProviderPageEnvelope",
        "/admin/models": "AdminModelPageEnvelope",
        "/generations": "IndexGenerationPageEnvelope",
    }

    assert set(paged_paths) == _backend_paged_get_paths()

    for path, item in spec["paths"].items():
        operation = item.get("get")
        if operation is None:
            continue
        names = {parameter["name"] for parameter in operation.get("parameters", [])}
        if path in paged_paths:
            assert {"limit", "cursor"}.issubset(names), path
            response = operation["responses"]["200"]["content"]["application/json"][
                "schema"
            ]
            assert response["$ref"] == "#/components/schemas/{0}".format(
                paged_paths[path]
            ), path
        else:
            assert "limit" not in names, path
            assert "cursor" not in names, path

    item_schemas = {
        "AdminUserPageEnvelope": "AdminUser",
        "TeamPageEnvelope": "Team",
        "TeamMemberPageEnvelope": "TeamMember",
        "KnowledgeBasePageEnvelope": "KnowledgeBase",
        "KnowledgeBaseMemberPageEnvelope": "KnowledgeBaseMember",
        "DocumentPageEnvelope": "Document",
        "DocumentVersionPageEnvelope": "DocumentVersion",
        "DocumentGrantPageEnvelope": "DocumentGrant",
        "IngestionRunPageEnvelope": "IngestionRun",
        "DocumentTaskPageEnvelope": "DocumentTask",
        "ChunkPageEnvelope": "Chunk",
        "DocumentChunkPageEnvelope": "DocumentChunk",
        "ChunkHistoryPageEnvelope": "ChunkHistory",
        "ChatPageEnvelope": "Chat",
        "MessagePageEnvelope": "Message",
        "RetrievalTracePageEnvelope": "RetrievalTrace",
        "EvaluationDatasetPageEnvelope": "EvaluationDataset",
        "EvaluationCasePageEnvelope": "EvaluationCase",
        "EvaluationRunPageEnvelope": "EvaluationRun",
        "SourceConnectionPageEnvelope": "SourceConnection",
        "CredentialPageEnvelope": "Credential",
        "ProviderPageEnvelope": "Provider",
        "ModelCallPageEnvelope": "ModelCall",
        "AuditLogPageEnvelope": "AuditLog",
        "AdminProviderPageEnvelope": "AdminProvider",
        "AdminModelPageEnvelope": "AdminModel",
        "IndexGenerationPageEnvelope": "IndexGeneration",
    }
    for envelope, item_schema in item_schemas.items():
        assert envelope in schemas, envelope
        assert item_schema in schemas, item_schema
        assert (
            schemas[envelope]["allOf"][0]["$ref"]
            == "#/components/schemas/PageEnvelope"
        ), envelope
        assert (
            schemas[envelope]["allOf"][1]["properties"]["data"]["items"]["$ref"]
            == "#/components/schemas/{0}".format(item_schema)
        ), envelope

    assert spec["paths"]["/sources"]["get"]["parameters"][1] == {
        "name": "kb_id",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
    }
    assert {
        parameter["name"]
        for parameter in spec["paths"]["/evals/runs"]["get"]["parameters"]
    } == {"team_id", "dataset_id", "limit", "cursor"}


def test_p0_write_status_codes_match_backend_handlers():
    paths = _spec()["paths"]
    expected = {
        "/auth/login": "200",
        "/admin/users/create": "201",
        "/admin/users/update": "200",
        "/auth/refresh": "200",
        "/auth/logout": "204",
        "/users/update": "200",
        "/auth/password/change": "204",
        "/teams/create": "201",
        "/teams/update": "200",
        "/invitations/create": "201",
        "/invitations/accept": "200",
        "/members/update": "200",
        "/members/remove": "200",
        "/members/transfer-documents": "202",
        "/kbs/create": "201",
        "/kbs/update": "200",
        "/kbs/archive": "202",
        "/kbs/policy/update": "200",
        "/kbs/members/update": "200",
        "/docs/upload": "202",
        "/docs/update": "200",
        "/docs/delete": "202",
        "/docs/restore": "202",
        "/docs/rebuild": "202",
        "/docs/grants/create": "201",
        "/docs/grants/revoke": "200",
        "/sources/github/create": "201",
        "/sources/update": "200",
        "/sources/delete": "200",
        "/sources/sync": "202",
        "/sources/pause": "200",
        "/sources/resume": "200",
        "/credentials/create": "201",
        "/credentials/delete": "200",
        "/ingestions/retry": "202",
        "/ingestions/cancel": "202",
        "/chunks/update": "200",
        "/chunks/disable": "200",
        "/chunks/enable": "200",
        "/chunks/regenerate": "202",
        "/chunks/bulk": "200",
        "/chats/create": "201",
        "/chats/update": "200",
        "/chats/delete": "200",
        "/chats/ask": "200",
        "/messages/cancel": "202",
        "/messages/feedback": "201",
        "/evals/datasets/create": "201",
        "/evals/datasets/update": "200",
        "/evals/datasets/archive": "200",
        "/evals/datasets/cases/create": "201",
        "/evals/datasets/cases/update": "200",
        "/evals/datasets/cases/delete": "200",
        "/evals/datasets/import": "201",
        "/evals/runs/start": "202",
        "/evals/runs/cancel": "202",
        "/model-policy/update": "200",
        "/providers/create": "201",
        "/providers/models": "200",
        "/providers/test": "200",
        "/admin/model-policy/update": "200",
        "/admin/providers/create": "201",
        "/admin/providers/models": "200",
        "/admin/providers/update": "200",
        "/admin/models/update": "200",
        "/generations/validate": "202",
        "/generations/reindex": "202",
        "/generations/activate": "202",
        "/generations/rollback": "202",
    }

    assert set(expected) == {
        path for path, item in paths.items() if "post" in item
    }
    for path, status in expected.items():
        assert status in paths[path]["post"]["responses"], path
        assert set(paths[path]["post"]["responses"]) == {status, "default"}


def test_provider_contract_supports_three_formats_and_write_only_api_keys():
    schemas = _spec()["components"]["schemas"]

    assert schemas["ProviderType"]["enum"] == [
        "openai_responses",
        "openai_chat_completions",
        "anthropic_messages",
    ]
    for schema_name in ("ProviderCreateBody", "AdminProviderCreateBody"):
        schema = schemas[schema_name]
        assert "api_key" in schema["properties"]
        assert schema["properties"]["api_key"]["writeOnly"] is True
        assert schema["properties"]["provider_type"]["$ref"].endswith("/ProviderType")
    assert schemas["AdminProviderUpdateBody"]["properties"]["api_key"]["writeOnly"] is True


def test_unimplemented_p1_routes_are_not_in_p0_contract():
    paths = _spec()["paths"]

    assert {
        "/auth/password/forgot",
        "/traces/replay",
        "/evals/comparisons/create",
        "/evals/comparisons/detail",
        "/gaps",
        "/gaps/update",
        "/gaps/promote",
    }.isdisjoint(paths)


def test_core_response_schemas_include_handler_fields():
    schemas = _spec()["components"]["schemas"]
    expected = {
        "Document": {
            "id",
            "knowledge_base_id",
            "file_name",
            "source_type",
            "product",
            "version_values",
            "visibility",
            "data_classification",
            "doc_status",
            "deleted_at",
            "purged_at",
            "version",
            "created_at",
            "updated_at",
        },
        "Chunk": {
            "id",
            "document_id",
            "document_version_id",
            "content",
            "heading_path",
            "source_locator",
            "status",
            "quality_flags",
            "version",
            "index_generation",
            "created_at",
            "updated_at",
        },
        "Chat": {
            "id",
            "team_id",
            "user_id",
            "title",
            "knowledge_base_ids",
            "version",
            "created_at",
            "updated_at",
        },
        "Message": {
            "id",
            "chat_id",
            "role",
            "content",
            "status",
            "trace_id",
            "citation_ids",
            "refusal_reason",
            "created_at",
        },
        "RetrievalTrace": {
            "id",
            "trace_id",
            "team_id",
            "chat_id",
            "message_id",
            "engine_mode",
            "original_query",
            "rewritten_query",
            "filters",
            "bm25_candidates",
            "dense_candidates",
            "rrf_candidates",
            "rerank_candidates",
            "final_context",
            "stage_latency_ms",
            "degraded",
            "error_code",
            "model",
            "feedback",
            "created_at",
        },
        "IndexGeneration": {
            "id",
            "team_id",
            "status",
            "chunk_count",
            "embedding_model",
            "error_message",
            "validation_errors",
            "created_at",
            "validated_at",
            "activated_at",
        },
        "AuditLog": {
            "id",
            "team_id",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "details",
            "created_at",
        },
        "GenerationReindex": {"generation", "run"},
        "GenerationValidation": {
            "generation_id",
            "status",
            "passed",
            "errors",
            "checked_chunks",
            "validated_at",
        },
    }

    for name, fields in expected.items():
        assert fields == set(schemas[name]["properties"]), name
        assert set(schemas[name]["required"]) == fields, name


def test_all_component_refs_resolve():
    spec = _spec()
    references = []

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "$ref" and child.startswith("#/components/"):
                    references.append(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(spec)
    for reference in set(references):
        _, _, section, name = reference.split("/", 3)
        assert name in spec["components"][section], reference


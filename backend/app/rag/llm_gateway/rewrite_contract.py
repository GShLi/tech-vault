from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


MAX_REWRITE_CHARS = 4000
MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_CHARS = 1000
MAX_VERSION_VALUES = 5
MAX_FACET_VALUES = 200

QUERY_REWRITE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "rewritten_query": {"type": "string"},
        "filters": {
            "type": "object",
            "properties": {
                "product": {
                    "anyOf": [{"type": "string"}, {"type": "null"}]
                },
                "version_values": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["product", "version_values"],
            "additionalProperties": False,
        },
    },
    "required": ["rewritten_query", "filters"],
    "additionalProperties": False,
}

REWRITE_SYSTEM_PROMPT = """You rewrite the latest user question into one self-contained search query for a technical knowledge base retrieval system, and extract only the metadata filters explicitly supported by the provided filter schema.

Rules:
- Use conversation history only to resolve references and omitted context.
- Resolve pronouns only when exactly one clear antecedent exists; otherwise keep the original question unchanged.
- Resolve a pronoun to the primary entity established by the latest user-assistant exchange.
- Prefer the subject of the latest user question; if the assistant answer resolves that subject to a primary name, use that primary name.
- Secondary aliases, alternate spellings, or contradictory examples mentioned in the assistant answer are not competing antecedents unless the user explicitly asks about them.
- Preserve the user's language, intent, entities, versions, code identifiers, error messages, and constraints.
- Add product/version filters only when they are explicit in the question or unambiguous from the recent conversation.
- Never invent facts, products, versions, or requirements.
- Do not answer, explain, translate, or split the question.
- If no rewrite is needed, return the original question unchanged.
- Return JSON only, matching the provided schema."""


class RewriteValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ParsedRewrite:
    rewritten_query: str
    extracted_filters: Dict[str, Any]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _message_value(item: Any, key: str) -> str:
    if isinstance(item, dict):
        value = item.get(key)
    else:
        value = getattr(item, key, None)
    return value if isinstance(value, str) else ""


def _truncate_history(history: Sequence[Any]) -> List[str]:
    lines: List[str] = []
    for item in list(history)[-MAX_HISTORY_MESSAGES:]:
        role = _message_value(item, "role").lower()
        if role not in {"user", "assistant"}:
            continue
        content = _message_value(item, "content").strip()[:MAX_HISTORY_CHARS]
        if content:
            lines.append("{0}: {1}".format(role, content))
    return lines


def build_rewrite_prompt(
    *,
    question: str,
    history: Sequence[Any] = (),
    product: Optional[str] = None,
    version_values: Sequence[str] = (),
    allowed_products: Sequence[str] = (),
    allowed_versions: Sequence[str] = (),
) -> Tuple[str, str]:
    history_lines = _truncate_history(history)
    allowed_product_values = list(allowed_products)[:MAX_FACET_VALUES]
    allowed_version_values = list(allowed_versions)[:MAX_FACET_VALUES]
    sections = [
        "Known product: {0}".format(product or "(none)"),
        "Known version: {0}".format(", ".join(version_values) or "(none)"),
        "Allowed products: {0}".format(
            json.dumps(allowed_product_values, ensure_ascii=False)
        ),
        "Allowed versions: {0}".format(
            json.dumps(allowed_version_values, ensure_ascii=False)
        ),
        "Required JSON shape:\n{0}".format(
            json.dumps(QUERY_REWRITE_SCHEMA, ensure_ascii=False)
        ),
        "Conversation history:\n{0}".format(
            "\n".join(history_lines) if history_lines else "(none)"
        ),
        "Latest question:\n{0}".format(question.strip()),
    ]
    return REWRITE_SYSTEM_PROMPT, "\n\n".join(sections)


def parse_rewrite_payload(payload: Any) -> ParsedRewrite:
    if not isinstance(payload, dict):
        raise RewriteValidationError("invalid_json")
    expected_fields = {"rewritten_query", "filters"}
    if set(payload) != expected_fields:
        raise RewriteValidationError(
            "unexpected_field"
            if set(payload) - expected_fields
            else "missing_field"
        )
    rewritten_query = payload.get("rewritten_query")
    if not isinstance(rewritten_query, str):
        raise RewriteValidationError("invalid_query_type")
    rewritten_query = _normalize_text(rewritten_query)
    if not rewritten_query or len(rewritten_query) > MAX_REWRITE_CHARS:
        raise RewriteValidationError("invalid_query_length")

    filters = payload.get("filters")
    if not isinstance(filters, dict):
        raise RewriteValidationError("invalid_filters_type")
    expected_filter_fields = {"product", "version_values"}
    if set(filters) != expected_filter_fields:
        raise RewriteValidationError(
            "unexpected_field"
            if set(filters) - expected_filter_fields
            else "missing_field"
        )
    product = filters.get("product")
    if product is not None and not isinstance(product, str):
        raise RewriteValidationError("invalid_filter_type")
    product = _normalize_text(product) if isinstance(product, str) else None
    if product == "":
        product = None

    raw_versions = filters.get("version_values")
    if not isinstance(raw_versions, list) or any(
        not isinstance(value, str) for value in raw_versions
    ):
        raise RewriteValidationError("invalid_filter_type")
    seen = set()
    versions = []
    for value in raw_versions:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            versions.append(normalized)
    return ParsedRewrite(
        rewritten_query=rewritten_query,
        extracted_filters={
            "product": product,
            "version_values": versions[:MAX_VERSION_VALUES],
        },
    )


def parse_rewrite_text(text: str) -> ParsedRewrite:
    stripped = text.strip()
    if stripped.startswith("```"):
        raise RewriteValidationError("markdown_not_allowed")
    try:
        payload = json.loads(stripped)
    except (TypeError, json.JSONDecodeError) as error:
        raise RewriteValidationError("invalid_json") from error
    return parse_rewrite_payload(payload)

"""Discover upstream model IDs for supported provider API formats."""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx


SUPPORTED_PROVIDER_TYPES = frozenset(
    {
        "openai_responses",
        "openai_chat_completions",
        "anthropic_messages",
    }
)
_OPERATION_SUFFIXES = (
    "/chat/completions",
    "/responses",
    "/completions",
    "/messages",
)
_ANTHROPIC_VERSION = "2023-06-01"


class ModelDiscoveryError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def normalize_model_list_url(base_url: str) -> str:
    normalized = base_url.strip()
    if not normalized:
        raise ModelDiscoveryError(
            400,
            "INVALID_ARGUMENT",
            "Base URL is required.",
        )
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ModelDiscoveryError(
            400,
            "INVALID_ARGUMENT",
            "Base URL must be an absolute HTTP or HTTPS URL.",
        )

    path = parsed.path.rstrip("/")
    if path.endswith("/models"):
        model_path = path
    else:
        for suffix in _OPERATION_SUFFIXES:
            if path.endswith(suffix):
                path = path[: -len(suffix)].rstrip("/")
                break
        model_path = path + ("/models" if path.endswith("/v1") else "/v1/models")
    return urlunsplit((parsed.scheme, parsed.netloc, model_path, "", ""))


def _headers(provider_type: str, api_key: str) -> dict[str, str]:
    if provider_type == "anthropic_messages":
        return {
            "Accept": "application/json",
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }
    return {
        "Accept": "application/json",
        "Authorization": "Bearer {0}".format(api_key),
    }


def _model_ids(payload: object) -> tuple[List[str], bool, Optional[str]]:
    if not isinstance(payload, dict):
        raise ValueError("model list response must be an object")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("model list response must contain a data array")
    ids = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            model_id = row["id"].strip()
            if model_id and model_id not in ids:
                ids.append(model_id)
    has_more = bool(payload.get("has_more"))
    last_id = payload.get("last_id")
    return ids, has_more, last_id if isinstance(last_id, str) else None


def discover_models(
    *,
    provider_type: str,
    base_url: str,
    api_key: str,
    timeout: float = 15.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> List[str]:
    if provider_type not in SUPPORTED_PROVIDER_TYPES:
        raise ModelDiscoveryError(
            400,
            "INVALID_ARGUMENT",
            "Unsupported provider type.",
        )
    if not api_key.strip():
        raise ModelDiscoveryError(
            400,
            "INVALID_ARGUMENT",
            "API Key is required.",
        )

    url = normalize_model_list_url(base_url)
    headers = _headers(provider_type, api_key.strip())
    discovered: List[str] = []
    pending_error: Optional[ModelDiscoveryError] = None
    try:
        with httpx.Client(
            timeout=timeout,
            transport=transport,
            trust_env=False,
        ) as client:
            after_id = None
            for _page in range(10):
                params = None
                if provider_type == "anthropic_messages":
                    params = {"limit": 1000}
                    if after_id:
                        params["after_id"] = after_id
                response = client.get(url, headers=headers, params=params)
                if response.status_code in {401, 403}:
                    pending_error = ModelDiscoveryError(
                        400,
                        "MODEL_LIST_AUTH_FAILED",
                        "Upstream rejected the API Key.",
                    )
                    break
                if response.status_code == 404:
                    pending_error = ModelDiscoveryError(
                        502,
                        "MODEL_LIST_UNSUPPORTED",
                        "Upstream does not provide a model list endpoint.",
                    )
                    break
                response.raise_for_status()
                try:
                    payload = response.json()
                    models, has_more, last_id = _model_ids(payload)
                except ValueError:
                    pending_error = ModelDiscoveryError(
                        502,
                        "MODEL_LIST_INVALID_RESPONSE",
                        "Upstream returned an invalid model list response.",
                    )
                    break
                for model_id in models:
                    if model_id not in discovered:
                        discovered.append(model_id)
                if (
                    provider_type != "anthropic_messages"
                    or not has_more
                    or not last_id
                ):
                    break
                after_id = last_id
    except httpx.HTTPStatusError as error:
        pending_error = ModelDiscoveryError(
            502,
            "MODEL_LIST_UNAVAILABLE",
            "Upstream model list request failed with HTTP {0}.".format(
                error.response.status_code
            ),
        )
    except Exception:
        pending_error = ModelDiscoveryError(
            502,
            "MODEL_LIST_UNAVAILABLE",
            "Upstream model list service is unavailable.",
        )
    if pending_error is not None:
        raise pending_error
    return discovered

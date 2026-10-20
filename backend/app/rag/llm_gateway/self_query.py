from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MAX_VERSION_VALUES = 5


@dataclass(frozen=True)
class SelfQueryApplication:
    applied_filters: Dict[str, Any]
    dropped_filters: List[Dict[str, Any]]


def _key(value: str) -> str:
    return re.sub(r"[\s-]+", "", value.strip().casefold())


def _canonical(value: str, allowed: Sequence[str]) -> Optional[str]:
    wanted = _key(value)
    for candidate in allowed:
        if _key(candidate) == wanted:
            return candidate
    return None


def _canonical_versions(
    values: Iterable[str],
    allowed: Sequence[str],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    applied = []
    dropped = []
    seen = set()
    for value in values:
        canonical = _canonical(value, allowed)
        if canonical is None:
            dropped.append(
                {
                    "field": "version_values",
                    "value": value,
                    "reason": "unknown_facet_value",
                }
            )
            continue
        if canonical not in seen:
            seen.add(canonical)
            applied.append(canonical)
    return applied[:MAX_VERSION_VALUES], dropped


def apply_self_query_filters(
    *,
    extracted_filters: Dict[str, Any],
    explicit_product: Optional[str],
    explicit_versions: Sequence[str],
    allowed_products: Sequence[str],
    allowed_versions: Sequence[str],
) -> SelfQueryApplication:
    dropped: List[Dict[str, Any]] = []
    extracted_product = extracted_filters.get("product")
    extracted_versions = list(extracted_filters.get("version_values") or [])

    if explicit_product:
        applied_product = (
            _canonical(explicit_product, allowed_products)
            or explicit_product.strip()
        )
        if (
            extracted_product
            and _key(str(extracted_product)) != _key(applied_product)
        ):
            dropped.append(
                {
                    "field": "product",
                    "value": extracted_product,
                    "reason": "user_override",
                }
            )
    elif extracted_product:
        applied_product = _canonical(
            str(extracted_product),
            allowed_products,
        )
        if applied_product is None:
            dropped.append(
                {
                    "field": "product",
                    "value": extracted_product,
                    "reason": "unknown_facet_value",
                }
            )
    else:
        applied_product = None

    if explicit_versions:
        applied_versions = [
            _canonical(value, allowed_versions) or value.strip()
            for value in explicit_versions
        ]
        if extracted_versions:
            if {_key(value) for value in extracted_versions} != {
                _key(value) for value in applied_versions
            }:
                dropped.append(
                    {
                        "field": "version_values",
                        "value": extracted_versions,
                        "reason": "user_override",
                    }
                )
    else:
        applied_versions, version_dropped = _canonical_versions(
            extracted_versions,
            allowed_versions,
        )
        dropped.extend(version_dropped)

    return SelfQueryApplication(
        applied_filters={
            "product": applied_product,
            "version_values": applied_versions,
        },
        dropped_filters=dropped,
    )

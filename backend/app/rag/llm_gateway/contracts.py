from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RewriteResult:
    original_query: str
    rewritten_query: str
    changed: bool
    route: str
    model_id: str
    provider_id: Optional[str] = None
    structured_mode: Optional[str] = None
    extracted_filters: Dict[str, Any] = field(default_factory=dict)
    applied_filters: Dict[str, Any] = field(default_factory=dict)
    dropped_filters: List[Dict[str, Any]] = field(default_factory=list)
    fallback_reason: Optional[str] = None
    validation_error: Optional[str] = None
    context_used: Dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DomainEvent:
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    tenant_id: str | None = None
    user_id: str | None = None


def emit(name: str, **payload: Any) -> DomainEvent:
    return DomainEvent(name=name, payload=dict(payload))

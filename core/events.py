from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict
from uuid import UUID, uuid4

from django.db import transaction
from django.dispatch import Signal

from core.context import get_tenant

domain_event = Signal()


@dataclass
class DomainEvent:
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    tenant_id: str | None = None
    user_id: str | None = None


def emit(
    name: str,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    **payload: Any,
) -> DomainEvent:
    tenant = get_tenant()
    if tenant_id is None and tenant is not None:
        tenant_id = str(tenant.pk)
    event = DomainEvent(
        name=name,
        payload=dict(payload),
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if tenant_id is not None:
        from accounting.models import EventInbox

        EventInbox.objects.create(
            tenant_id=UUID(tenant_id),
            event_name=event.name,
            payload=event.payload,
            idempotency_key=uuid4().hex,
        )
        transaction.on_commit(
            lambda: domain_event.send(sender=emit, event=event),
            robust=True,
        )
    return event

"""Audit logging service."""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from dentiva.core.dates import local_now
from dentiva.core.permissions import Permission, Principal, policy
from dentiva.models import AuditEvent

log = logging.getLogger(__name__)


def _principal_id(principal: Principal | None) -> int | None:
    return principal.user_id if principal else None


def record(
    session: Session,
    principal: Principal | None,
    action: str,
    *,
    entity_type: str = "",
    entity_id: int | None = None,
    summary: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        timestamp=local_now(),
        user_id=_principal_id(principal),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        before_json=json.dumps(before, default=str) if before else None,
        after_json=json.dumps(after, default=str) if after else None,
        ip_or_machine="",
    )
    session.add(event)
    log.info("AUDIT %s %s/%s: %s", action, entity_type, entity_id, summary)
    return event


def list_events(
    session: Session,
    principal: Principal,
    *,
    limit: int = 200,
    offset: int = 0,
    action: str | None = None,
    entity_type: str | None = None,
    user_id: int | None = None,
) -> list[AuditEvent]:
    policy.require(principal, Permission.AUDIT_LOG_VIEW)
    from sqlalchemy import select
    q = select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit).offset(offset)
    if action:
        q = q.where(AuditEvent.action == action)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if user_id is not None:
        q = q.where(AuditEvent.user_id == user_id)
    return list(session.scalars(q))

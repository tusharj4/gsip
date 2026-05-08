"""Maker-Checker State Machine for GIS Layer approval.

Workflow:
  draft → submitted (maker uploads data)
    → approved  (checker reviews and approves)
    → published (approver makes live)
    → rejected  (checker rejects; returns to draft)

Every transition writes an immutable audit_log entry.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.layer import GISLayer

logger = logging.getLogger(__name__)

# Valid transitions: {current_status: [allowed_next_statuses]}
TRANSITIONS: dict[str, list[str]] = {
    "draft":     ["submitted"],
    "submitted": ["approved", "rejected"],
    "approved":  ["published", "rejected"],
    "rejected":  ["draft"],
    "published": [],  # terminal — requires admin override
}

# Which actor role is authorised for each target status
ROLE_REQUIRED: dict[str, str] = {
    "submitted": "maker",
    "approved":  "checker",
    "rejected":  "checker",
    "published": "approver",
    "draft":     "maker",  # re-open after rejection
}


class DataValidator:
    """Handles layer status transitions and audit logging."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def transition(
        self,
        layer_id: uuid.UUID,
        target_status: str,
        actor_id: uuid.UUID | None,
        actor_role: str,
        notes: str | None = None,
    ) -> GISLayer:
        """Transition a layer to target_status if the actor is authorised.

        Raises ValueError on invalid transitions.
        Writes an audit_log entry regardless of success/failure path.
        """
        layer = await self._db.get(GISLayer, layer_id)
        if not layer:
            raise ValueError(f"Layer {layer_id} not found")

        allowed = TRANSITIONS.get(layer.status, [])
        if target_status not in allowed:
            raise ValueError(
                f"Cannot transition '{layer.status}' → '{target_status}'. "
                f"Allowed from '{layer.status}': {allowed or ['none']}"
            )

        required_role = ROLE_REQUIRED.get(target_status)
        if required_role and actor_role != required_role:
            raise PermissionError(
                f"Status '{target_status}' requires role '{required_role}', got '{actor_role}'"
            )

        prev_status = layer.status
        layer.status = target_status

        # Write audit entry
        audit = AuditLog(
            entity_type="gis_layer",
            entity_id=layer_id,
            action=target_status,
            actor_id=actor_id,
            actor_role=actor_role,
            notes=notes,
            diff={"from": prev_status, "to": target_status},
        )
        self._db.add(audit)
        await self._db.flush()

        logger.info(
            "Layer %s ('%s') transitioned %s → %s by %s (%s)",
            layer_id, layer.name, prev_status, target_status, actor_id, actor_role,
        )
        return layer

    async def get_audit_history(self, layer_id: uuid.UUID) -> list[dict[str, Any]]:
        """Return the full audit trail for a layer, newest first."""
        result = await self._db.execute(
            text("""
                SELECT action, actor_id, actor_role, notes, diff, created_at
                FROM audit_log
                WHERE entity_type = 'gis_layer' AND entity_id = :lid
                ORDER BY created_at DESC
            """),
            {"lid": str(layer_id)},
        )
        return [
            {
                "action": row.action,
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "actor_role": row.actor_role,
                "notes": row.notes,
                "diff": row.diff,
                "timestamp": row.created_at.isoformat(),
            }
            for row in result.fetchall()
        ]

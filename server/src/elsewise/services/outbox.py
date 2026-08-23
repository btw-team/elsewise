from typing import Any

from sqlalchemy.orm import Session

from elsewise.persistence.models import UiEventRecord


def emit_ui_event(
    db: Session,
    event_type: str,
    aggregate_id: str | None,
    payload: dict[str, Any],
) -> UiEventRecord:
    event = UiEventRecord(
        event_type=event_type,
        aggregate_id=aggregate_id,
        payload=payload,
    )
    db.add(event)
    db.flush()
    return event

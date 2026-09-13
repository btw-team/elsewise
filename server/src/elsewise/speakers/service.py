from sqlalchemy import select

from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptureSourceRecord,
    SourceEpochRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
)
from elsewise.services.speaker_identity import classify_speaker, own_speaker_names
from elsewise.settings.config import GlobalSettings


def refresh_caption_speaker_assignments(database: Database, settings: GlobalSettings) -> int:
    """Re-evaluate caption labels after the user changes own-speaker names."""
    configured_names = own_speaker_names(settings)
    changed = 0
    with database.transaction() as db:
        rows = db.execute(
            select(UtteranceSpeakerAssignmentRecord, CaptureSourceRecord.platform)
            .join(
                UtteranceRecord,
                UtteranceRecord.id == UtteranceSpeakerAssignmentRecord.utterance_id,
            )
            .join(SourceEpochRecord, SourceEpochRecord.id == UtteranceRecord.source_epoch_id)
            .join(CaptureSourceRecord, CaptureSourceRecord.id == SourceEpochRecord.source_id)
            .where(UtteranceSpeakerAssignmentRecord.provenance == "browser.caption_label")
        ).all()
        for assignment, platform in rows:
            classified = classify_speaker(
                assignment.display_label,
                platform,
                configured_names,
            )
            role = "remote" if classified == "other" else classified
            if assignment.speaker_role == role:
                continue
            assignment.speaker_role = role
            assignment.confidence = 1.0 if role != "unknown" else 0.0
            assignment.revision += 1
            changed += 1
    return changed

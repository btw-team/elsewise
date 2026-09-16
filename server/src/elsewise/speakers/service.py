from sqlalchemy import select

from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptureSourceRecord,
    SourceEpochRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
)
from elsewise.services.errors import ServiceError
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


def assign_speaker_manually(
    database: Database,
    utterance_id: str,
    *,
    profile_id: str | None,
    display_label: str | None,
    apply_to_anonymous_track: bool,
    use_voice_samples: bool,
    clear: bool = False,
) -> int:
    from elsewise.persistence.models import SpeakerProfileRecord

    if use_voice_samples:
        raise ServiceError(
            "speaker_enrollment_unavailable",
            "Voice sample enrollment is not available until the speaker backend is calibrated.",
            status_code=409,
        )
    with database.transaction() as db:
        utterance = db.get(UtteranceRecord, utterance_id)
        if utterance is None:
            raise ServiceError("not_found", "Utterance not found.", status_code=404)
        profile = db.get(SpeakerProfileRecord, profile_id) if profile_id else None
        if profile_id is not None and profile is None:
            raise ServiceError("not_found", "Speaker profile not found.", status_code=404)
        assignment = db.scalar(
            select(UtteranceSpeakerAssignmentRecord).where(
                UtteranceSpeakerAssignmentRecord.utterance_id == utterance.id
            )
        )
        created = assignment is None
        if assignment is None:
            assignment = UtteranceSpeakerAssignmentRecord(
                utterance_id=utterance.id,
                revision=1,
                speaker_role="remote",
            )
            db.add(assignment)
            db.flush()
        track_id = assignment.anonymous_track_id
        targets = [assignment]
        if apply_to_anonymous_track and track_id:
            targets = list(
                db.scalars(
                    select(UtteranceSpeakerAssignmentRecord)
                    .join(UtteranceRecord)
                    .where(
                        UtteranceSpeakerAssignmentRecord.anonymous_track_id == track_id,
                        UtteranceRecord.session_id == utterance.session_id,
                    )
                )
            )
        label = profile.display_name if profile is not None else display_label
        for target in targets:
            if not (created and target is assignment):
                target.revision += 1
            target.speaker_role = "unknown" if clear else "remote"
            target.speaker_profile_id = None if clear else (profile.id if profile else None)
            target.display_label = None if clear else label
            target.confidence = 0.0 if clear else 1.0
            target.provenance = "manual.clear" if clear else "manual"
            target.evidence_refs = []
        return len(targets)

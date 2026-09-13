from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

SpeakerRole = Literal["self", "remote", "unknown"]


class AssignmentApplyResult(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SpeakerAssignment:
    utterance_id: str
    revision: int
    speaker_role: SpeakerRole
    confidence: float
    provenance: str
    display_label: str | None = None
    profile_id: str | None = None
    anonymous_track: str | None = None
    evidence_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.utterance_id or len(self.utterance_id) > 256:
            raise ValueError("utterance_id must contain between 1 and 256 characters")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.provenance or len(self.provenance) > 128:
            raise ValueError("provenance must contain between 1 and 128 characters")
        for value, maximum, field_name in (
            (self.display_label, 512, "display_label"),
            (self.profile_id, 36, "profile_id"),
            (self.anonymous_track, 128, "anonymous_track"),
        ):
            if value is not None and (not value or len(value) > maximum):
                raise ValueError(f"{field_name} must contain between 1 and {maximum} characters")
        if len(self.evidence_event_ids) > 32 or any(
            not event_id or len(event_id) > 256 for event_id in self.evidence_event_ids
        ):
            raise ValueError("evidence_event_ids must contain at most 32 bounded values")


@dataclass(slots=True)
class SpeakerAssignmentMachine:
    assignments: dict[str, SpeakerAssignment] = field(default_factory=dict)

    def apply(self, assignment: SpeakerAssignment) -> AssignmentApplyResult:
        current = self.assignments.get(assignment.utterance_id)
        if current == assignment:
            return AssignmentApplyResult.DUPLICATE
        if current is not None and assignment.revision <= current.revision:
            return AssignmentApplyResult.STALE
        self.assignments[assignment.utterance_id] = assignment
        return AssignmentApplyResult.APPLIED

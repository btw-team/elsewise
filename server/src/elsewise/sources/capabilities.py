from enum import StrEnum


class SourceCapability(StrEnum):
    CAPTIONS = "captions"
    SPEAKER_LABELS = "speaker_labels"
    DAEMON_CONTROL = "daemon_source_control"
    NORMALIZED_EVIDENCE = "normalized_evidence"

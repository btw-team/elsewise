from enum import StrEnum


class SourceCapability(StrEnum):
    AUDIO_PCM = "audio_pcm"
    DEVICE_DISCOVERY = "device_discovery"
    PROCESS_TARGETS = "process_targets"
    PERMISSIONS = "permissions"
    HEALTH = "health"
    CAPTIONS = "captions"
    SPEAKER_LABELS = "speaker_labels"
    PARTICIPANTS = "participants"
    ACTIVE_SPEAKER = "active_speaker"
    DAEMON_CONTROL = "daemon_source_control"
    NORMALIZED_EVIDENCE = "normalized_evidence"

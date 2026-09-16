from enum import StrEnum


class SourceCapability(StrEnum):
    AUDIO_PCM = "audio_pcm"
    DEVICE_DISCOVERY = "device_discovery"
    PROCESS_TARGETS = "process_targets"
    PERMISSIONS = "permissions"
    HEALTH = "health"
    CAPTIONS = "captions"
    SPEAKER_LABELS = "speaker_labels"
    ACTIVITY_LIFECYCLE = "activity_lifecycle"
    PARTICIPANTS = "participants"
    SELF_IDENTITY = "self_identity"
    ACTIVE_SPEAKER = "active_speaker"
    MUTE_STATE = "mute_state"
    HAND_RAISE = "hand_raise"
    PRESENTATION = "presentation"
    CHAT = "chat"
    REACTIONS = "reactions"
    RECORDING_STATE = "recording_state"
    ACCESSIBILITY_HEALTH = "accessibility_health"
    DAEMON_CONTROL = "daemon_source_control"
    NORMALIZED_EVIDENCE = "normalized_evidence"

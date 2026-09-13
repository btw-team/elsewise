from elsewise.sources.capabilities import SourceCapability
from elsewise.sources.contracts import SourceCategory, SourceRole
from elsewise.sources.registry import SourceDriver

DRIVER = SourceDriver(
    id="native_audio",
    version="1",
    category=SourceCategory.AUDIO,
    source_kinds=frozenset({"native_microphone", "native_process_audio", "native_system_audio"}),
    supported_roles=frozenset({SourceRole.SELF, SourceRole.REMOTE}),
    capabilities=frozenset(
        {
            SourceCapability.AUDIO_PCM,
            SourceCapability.DEVICE_DISCOVERY,
            SourceCapability.PROCESS_TARGETS,
            SourceCapability.PERMISSIONS,
            SourceCapability.HEALTH,
        }
    ),
    required_capabilities=frozenset({SourceCapability.AUDIO_PCM, SourceCapability.HEALTH}),
)

from elsewise.sources.capabilities import SourceCapability
from elsewise.sources.contracts import SourceCategory, SourceRole
from elsewise.sources.registry import SourceDriver

DRIVER = SourceDriver(
    id="synthetic_audio",
    version="1",
    category=SourceCategory.SYNTHETIC,
    source_kinds=frozenset({"synthetic_audio"}),
    supported_roles=frozenset({SourceRole.SELF, SourceRole.REMOTE}),
    capabilities=frozenset({SourceCapability.AUDIO_PCM, SourceCapability.HEALTH}),
    required_capabilities=frozenset({SourceCapability.AUDIO_PCM, SourceCapability.HEALTH}),
)

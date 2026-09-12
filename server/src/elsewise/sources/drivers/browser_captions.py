from elsewise.sources.capabilities import SourceCapability
from elsewise.sources.registry import SourceDriver

DRIVER = SourceDriver(
    id="browser_captions",
    version="2",
    capabilities=frozenset(SourceCapability),
    required_capabilities=frozenset(
        {
            SourceCapability.CAPTIONS,
            SourceCapability.DAEMON_CONTROL,
            SourceCapability.NORMALIZED_EVIDENCE,
        }
    ),
)

from elsewise.sources.capabilities import SourceCapability
from elsewise.sources.registry import SourceDriver

# The synthetic browser fixture uses the production transport and lifecycle
# contract; only its DOM producer is deterministic.
DRIVER = SourceDriver(
    id="synthetic_captions",
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

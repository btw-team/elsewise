from elsewise.sources.capabilities import SourceCapability
from elsewise.sources.contracts import SourceCategory, SourceRole
from elsewise.sources.registry import SourceDriver

# The synthetic browser fixture uses the production transport and lifecycle
# contract; only its DOM producer is deterministic.
DRIVER = SourceDriver(
    id="synthetic_semantic",
    version="3",
    category=SourceCategory.SEMANTIC,
    source_kinds=frozenset({"browser_semantic"}),
    supported_roles=frozenset({SourceRole.SECONDARY}),
    capabilities=frozenset(SourceCapability),
    required_capabilities=frozenset(
        {
            SourceCapability.CAPTIONS,
            SourceCapability.DAEMON_CONTROL,
            SourceCapability.NORMALIZED_EVIDENCE,
        }
    ),
)

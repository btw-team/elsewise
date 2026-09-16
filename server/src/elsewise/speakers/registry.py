from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    SpeakerProfileAliasRecord,
    SpeakerProfileRecord,
    SpeakerPrototypeRecord,
    SpeakerSemanticIdentityRecord,
)

MAX_PROFILE_NAME_LENGTH = 512
MAX_PROTOTYPES_PER_PROFILE = 24


@dataclass(frozen=True, slots=True)
class SpeakerProfile:
    id: str
    display_name: str
    aliases: tuple[str, ...]
    prototype_count: int


def normalize_alias(value: str) -> str:
    normalized = " ".join(value.casefold().split())
    if not normalized or len(normalized) > MAX_PROFILE_NAME_LENGTH:
        raise ValueError("speaker alias must contain between 1 and 512 characters")
    return normalized


class SpeakerRegistry:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, display_name: str, *, aliases: tuple[str, ...] = ()) -> SpeakerProfile:
        normalized_name = normalize_alias(display_name)
        unique_aliases: dict[str, str] = {}
        for alias in aliases:
            unique_aliases.setdefault(normalize_alias(alias), alias.strip())
        unique_aliases.pop(normalized_name, None)
        with self.database.transaction() as db:
            profile = SpeakerProfileRecord(display_name=display_name.strip())
            db.add(profile)
            db.flush()
            for normalized, alias in sorted(unique_aliases.items()):
                db.add(
                    SpeakerProfileAliasRecord(
                        profile_id=profile.id,
                        alias=alias,
                        normalized_alias=normalized,
                    )
                )
            profile_id = profile.id
        return self.require(profile_id)

    def list(self) -> tuple[SpeakerProfile, ...]:
        with self.database.transaction() as db:
            rows = list(
                db.scalars(
                    select(SpeakerProfileRecord).order_by(SpeakerProfileRecord.display_name)
                )
            )
            return tuple(self._payload(db, row) for row in rows)

    def require(self, profile_id: str) -> SpeakerProfile:
        with self.database.transaction() as db:
            row = db.get(SpeakerProfileRecord, profile_id)
            if row is None:
                raise KeyError(profile_id)
            return self._payload(db, row)

    def rename(self, profile_id: str, display_name: str) -> SpeakerProfile:
        normalize_alias(display_name)
        with self.database.transaction() as db:
            row = db.get(SpeakerProfileRecord, profile_id)
            if row is None:
                raise KeyError(profile_id)
            row.display_name = display_name.strip()
        return self.require(profile_id)

    def delete(self, profile_id: str) -> bool:
        with self.database.transaction() as db:
            row = db.get(SpeakerProfileRecord, profile_id)
            if row is None:
                return False
            db.delete(row)
            return True

    def add_prototype(
        self,
        profile_id: str,
        *,
        model_id: str,
        model_version: str,
        dimensions: int,
        embedding: bytes,
        quality: float,
        speech_duration_ms: int,
        source_type: str,
        consent_provenance: str,
        metadata: dict[str, object] | None = None,
    ) -> str:
        if dimensions < 1 or len(embedding) != dimensions * 4:
            raise ValueError("embedding must contain exactly one float32 vector")
        if not 0 <= quality <= 1:
            raise ValueError("quality must be between 0 and 1")
        if speech_duration_ms < 1:
            raise ValueError("speech duration must be positive")
        for value, maximum, name in (
            (model_id, 256, "model_id"),
            (model_version, 128, "model_version"),
            (source_type, 64, "source_type"),
            (consent_provenance, 128, "consent_provenance"),
        ):
            if not value or len(value) > maximum:
                raise ValueError(f"{name} must be bounded")
        with self.database.transaction() as db:
            profile = db.get(SpeakerProfileRecord, profile_id)
            if profile is None:
                raise KeyError(profile_id)
            prototypes = list(
                db.scalars(
                    select(SpeakerPrototypeRecord)
                    .where(SpeakerPrototypeRecord.profile_id == profile_id)
                    .order_by(SpeakerPrototypeRecord.created_at)
                )
            )
            if prototypes and any(
                item.model_id != model_id
                or item.model_version != model_version
                or item.dimensions != dimensions
                for item in prototypes
            ):
                raise ValueError("speaker profile embeddings must use one compatible model")
            if len(prototypes) >= MAX_PROTOTYPES_PER_PROFILE:
                raise ValueError("speaker profile prototype limit reached")
            record = SpeakerPrototypeRecord(
                profile_id=profile_id,
                model_id=model_id,
                model_version=model_version,
                dimensions=dimensions,
                embedding=embedding,
                quality=quality,
                speech_duration_ms=speech_duration_ms,
                source_type=source_type,
                consent_provenance=consent_provenance,
                metadata_json=dict(metadata or {}),
            )
            db.add(record)
            db.flush()
            return record.id

    def link_semantic_identity(
        self,
        profile_id: str,
        *,
        identity_kind: str,
        identity_digest: str,
        confidence: float,
        provenance: str,
    ) -> str:
        if len(identity_digest) != 64:
            raise ValueError("semantic identity digest must be SHA-256 sized")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        with self.database.transaction() as db:
            if db.get(SpeakerProfileRecord, profile_id) is None:
                raise KeyError(profile_id)
            record = SpeakerSemanticIdentityRecord(
                profile_id=profile_id,
                identity_kind=identity_kind,
                identity_digest=identity_digest,
                confidence=confidence,
                provenance=provenance,
            )
            db.add(record)
            db.flush()
            return record.id

    @staticmethod
    def _payload(db: Session, row: SpeakerProfileRecord) -> SpeakerProfile:
        aliases = tuple(
            db.scalars(
                select(SpeakerProfileAliasRecord.alias)
                .where(SpeakerProfileAliasRecord.profile_id == row.id)
                .order_by(SpeakerProfileAliasRecord.normalized_alias)
            )
        )
        prototype_count = db.scalar(
            select(func.count(SpeakerPrototypeRecord.id)).where(
                SpeakerPrototypeRecord.profile_id == row.id
            )
        ) or 0
        return SpeakerProfile(
            id=row.id,
            display_name=row.display_name,
            aliases=aliases,
            prototype_count=prototype_count,
        )

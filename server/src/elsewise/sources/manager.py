import asyncio
from time import monotonic_ns
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptureSourceRecord,
    PairedClientRecord,
    RecordingSegmentRecord,
    SessionRecord,
    SessionSourceBindingRecord,
    SourceEpochRecord,
    utc_now,
)
from elsewise.protocol.models import SourceDiscovered, SourceHealth
from elsewise.services.errors import ServiceError
from elsewise.services.outbox import emit_ui_event
from elsewise.sources.connections import BrowserConnectionRegistry
from elsewise.sources.contracts import SourceDescriptor, SourceRole
from elsewise.sources.registry import SourceDriverRegistry, default_source_registry

SOURCE_COMMAND_SECONDS = 2.0
ACTIVE_BINDING_STATES = ("starting", "active", "waiting", "degraded", "stopping")


class SourceManager:
    def __init__(
        self,
        database: Database,
        connections: BrowserConnectionRegistry | None = None,
        registry: SourceDriverRegistry | None = None,
    ) -> None:
        self.database = database
        self.connections = connections or BrowserConnectionRegistry()
        self.registry = registry or default_source_registry()

    def register_local(
        self,
        descriptor: SourceDescriptor,
        *,
        role: SourceRole,
        target_key: str,
        producer_epoch_id: str,
        sanitized_metadata: dict[str, object] | None = None,
    ) -> tuple[str, str | None]:
        try:
            UUID(descriptor.id)
        except ValueError as exc:
            raise ServiceError(
                "invalid_source_id", "Local source id must be a UUID.", status_code=422
            ) from exc
        driver = self.registry.require(descriptor.driver_id)
        if (
            descriptor.category is not driver.category
            or descriptor.kind not in driver.source_kinds
            or role not in driver.supported_roles
        ):
            raise ServiceError(
                "source_driver_mismatch",
                "The source descriptor is incompatible with its driver.",
                status_code=422,
            )
        if not driver.required_capabilities.issubset(descriptor.capabilities):
            raise ServiceError(
                "source_capabilities_missing",
                "The source does not advertise the capabilities required by its driver.",
                status_code=422,
            )
        if len(target_key) > 256 or not target_key:
            raise ServiceError(
                "invalid_source_target", "Local source target is invalid.", status_code=422
            )
        metadata = dict(sanitized_metadata or {})
        metadata["producer_epoch_id"] = producer_epoch_id[:128]
        with self.database.transition_lock, self.database.transaction() as db:
            source = db.get(CaptureSourceRecord, descriptor.id)
            if source is None:
                source = CaptureSourceRecord(
                    id=descriptor.id,
                    source_kind=descriptor.kind,
                    source_category=descriptor.category.value,
                    source_role=role.value,
                    target_key=target_key,
                    platform=descriptor.platform,
                    driver_id=descriptor.driver_id,
                    driver_version=descriptor.driver_version,
                    protocol_version=descriptor.protocol_version,
                    capabilities=sorted(descriptor.capabilities),
                    sanitized_metadata=metadata,
                )
                db.add(source)
                db.flush()
            else:
                source.target_key = target_key
                source.driver_version = descriptor.driver_version
                source.protocol_version = descriptor.protocol_version
                source.capabilities = sorted(descriptor.capabilities)
                source.sanitized_metadata = metadata
                source.connected = True
                source.available = True
                source.health_status = "available"
                source.last_error_code = None
                source.updated_at = utc_now()
            running = db.scalar(
                select(SessionRecord).where(SessionRecord.recording_status == "running")
            )
            epoch = None
            if running is not None and self._role_enabled(running, role.value):
                binding = self._active_binding(db, running.id, role.value)
                if binding is None or (
                    binding.source_id is None and binding.requested_mode == "auto"
                ):
                    self._bind_source(db, running, source, requested_mode="auto")
                    epoch = self._ensure_epoch(db, running, source, producer_epoch_id)
                    self._refresh_session_source_status(db, running)
                    emit_ui_event(
                        db,
                        "session.state",
                        running.id,
                        self._session_payload(db, running),
                    )
            emit_ui_event(db, "source.changed", source.id, self._source_payload(db, source, epoch))
            return source.id, epoch.id if epoch else None

    def discover(
        self, message: SourceDiscovered, *, paired_client_id: str
    ) -> tuple[str, str | None]:
        driver = self.registry.require(message.driver_id)
        advertised_capabilities = frozenset(message.capabilities)
        if not driver.required_capabilities.issubset(advertised_capabilities):
            raise ServiceError(
                "source_capabilities_missing",
                "The source does not advertise the capabilities required by its driver.",
                status_code=422,
            )
        if not advertised_capabilities.issubset(driver.capabilities):
            raise ServiceError(
                "unsupported_source_capability",
                "The source advertises an unsupported capability.",
                status_code=422,
            )
        observed_at = message.observed_at
        with self.database.transition_lock, self.database.transaction() as db:
            replaced_source_ids: set[str] = set()
            candidates = list(
                db.scalars(
                    select(CaptureSourceRecord)
                    .where(
                        CaptureSourceRecord.paired_client_id == paired_client_id,
                        CaptureSourceRecord.tab_instance_id == message.tab_instance_id,
                    )
                    .order_by(CaptureSourceRecord.created_at.desc())
                )
            )
            source = next(
                (item for item in candidates if item.activity_key == message.activity_key),
                None,
            )
            if source is None:
                for item in candidates:
                    item.available = False
                    item.connected = False
                    replaced_source_ids.add(item.id)
                source = CaptureSourceRecord(
                    paired_client_id=paired_client_id,
                    source_kind="browser_captions",
                    source_category="captions",
                    source_role="secondary",
                    platform=message.platform,
                    driver_id=message.driver_id,
                    driver_version=message.driver_version,
                    protocol_version=message.protocol_version,
                    tab_instance_id=message.tab_instance_id,
                    activity_key=message.activity_key,
                    capabilities=list(dict.fromkeys(message.capabilities))[:32],
                )
                db.add(source)
                db.flush()
            was_connected = source.connected
            source.platform = message.platform
            source.driver_id = message.driver_id
            source.driver_version = message.driver_version
            source.protocol_version = message.protocol_version
            source.connected = True
            source.available = message.health_status != "unavailable"
            source.health_status = message.health_status
            source.last_error_code = message.error_code
            source.last_event_at = observed_at
            source.sanitized_metadata = {"producer_epoch_id": message.producer_epoch_id}

            running = db.scalar(
                select(SessionRecord).where(SessionRecord.recording_status == "running")
            )
            binding = (
                self._active_binding(db, running.id, "secondary") if running is not None else None
            )
            if (
                running is not None
                and binding is not None
                and binding.source_id in replaced_source_ids
            ):
                binding.source_id = None
                binding.state = "waiting"
                binding.effective_mode = "unavailable"
                binding.reason = "activity_changed"
                for old_epoch in db.scalars(
                    select(SourceEpochRecord).where(
                        SourceEpochRecord.source_id.in_(replaced_source_ids),
                        SourceEpochRecord.session_id == running.id,
                        SourceEpochRecord.state.in_(("starting", "running")),
                    )
                ):
                    old_epoch.state = "stopped"
                    old_epoch.ended_at = utc_now()
                    old_epoch.end_reason = "activity_changed"
            if running is not None and (
                binding is None
                or (
                    binding.source_id is None
                    and binding.requested_mode == "auto"
                    and binding.reason != "activity_changed"
                )
            ):
                live = self._live_candidates(db, role="secondary")
                if len(live) == 1:
                    binding = self._bind_source(db, running, source, requested_mode="auto")
            reconnecting_epoch = db.scalar(
                select(SourceEpochRecord).where(
                    SourceEpochRecord.source_id == source.id,
                    SourceEpochRecord.session_id == (running.id if running else None),
                    SourceEpochRecord.producer_epoch_id == message.producer_epoch_id,
                    SourceEpochRecord.state.in_(("starting", "running")),
                )
            )
            epoch = self._ensure_epoch(db, running, source, message.producer_epoch_id)
            if epoch is not None and reconnecting_epoch is not None and not was_connected:
                epoch.reconnect_count += 1
            emit_ui_event(db, "source.changed", source.id, self._source_payload(db, source, epoch))
            if running is not None:
                self._refresh_session_source_status(db, running)
                emit_ui_event(db, "session.state", running.id, self._session_payload(db, running))
            log_event("source.discovered", source_id=source.id, platform=source.platform)
            return source.id, epoch.id if epoch else None

    def update_health(self, message: SourceHealth, *, paired_client_id: str) -> str:
        with self.database.transaction() as db:
            source = db.get(CaptureSourceRecord, str(message.source_id))
            if source is None or source.paired_client_id != paired_client_id:
                return "source_not_bound"
            lifecycle_changed = (
                source.health_status != message.health_status
                or source.available != (message.health_status != "unavailable")
                or source.last_error_code != message.error_code
            )
            source.health_status = message.health_status
            source.available = message.health_status != "unavailable"
            if message.error_code == "producer_disconnected":
                source.connected = False
            source.last_error_code = message.error_code
            source.last_event_at = message.observed_at
            epoch = (
                db.get(SourceEpochRecord, str(message.source_epoch_id))
                if message.source_epoch_id
                else None
            )
            if epoch is not None and epoch.source_id == source.id:
                epoch.last_health_status = message.health_status
                epoch.last_error_code = message.error_code
                epoch.dropped_event_count = max(
                    epoch.dropped_event_count, message.dropped_event_count
                )
                epoch.last_seen_at = message.observed_at
            running = db.scalar(
                select(SessionRecord).where(SessionRecord.recording_status == "running")
            )
            binding = (
                self._active_binding_for_source(db, running.id, source.id)
                if running is not None
                else None
            )
            if running is not None and binding is not None:
                binding.state = self._binding_state(source)
                binding.effective_mode = self._effective_mode(source)
                binding.reason = source.last_error_code
                previous_status = running.source_status
                self._refresh_session_source_status(db, running)
                session_changed = previous_status != running.source_status
                if session_changed:
                    emit_ui_event(
                        db, "session.state", running.id, self._session_payload(db, running)
                    )
            if lifecycle_changed:
                emit_ui_event(
                    db, "source.changed", source.id, self._source_payload(db, source, epoch)
                )
            return "applied"

    def attach_for_session(self, session_id: str) -> list[SourceEpochRecord]:
        with self.database.transition_lock, self.database.transaction() as db:
            session = db.get(SessionRecord, session_id)
            if session is None:
                raise ServiceError("session_not_found", "Session not found.", status_code=404)
            if session.recording_status != "running":
                return []
            epochs: list[SourceEpochRecord] = []
            for role in ("self", "remote", "secondary"):
                if not self._role_enabled(session, role):
                    self._ensure_disabled_binding(db, session, role)
                    continue
                binding = self._ensure_waiting_binding(db, session, role)
                source = (
                    db.get(CaptureSourceRecord, binding.source_id)
                    if binding.source_id is not None
                    else None
                )
                if source is None:
                    live = self._live_candidates(db, role=role)
                    if len(live) != 1:
                        continue
                    source = live[0]
                    binding = self._bind_source(db, session, source, requested_mode="auto")
                producer_epoch_id = str(
                    source.sanitized_metadata.get("producer_epoch_id", "unknown")
                )
                epoch = self._ensure_epoch(db, session, source, producer_epoch_id)
                if epoch is not None:
                    epochs.append(epoch)
            self._refresh_session_source_status(db, session)
            return epochs

    def select(
        self, session_id: str, source_id: str, *, role: str | None = None
    ) -> SourceEpochRecord:
        with self.database.transition_lock, self.database.transaction() as db:
            session = db.get(SessionRecord, session_id)
            source = db.get(CaptureSourceRecord, source_id)
            if session is None:
                raise ServiceError("session_not_found", "Session not found.", status_code=404)
            if session.recording_status != "running":
                raise ServiceError(
                    "session_not_running", "The session is not running.", status_code=409
                )
            if (
                source is None
                or not source.connected
                or not source.available
                or source.health_status == "unavailable"
            ):
                raise ServiceError(
                    "source_unavailable", "The source is not available.", status_code=409
                )
            selected_role = role or source.source_role
            if selected_role != source.source_role:
                raise ServiceError(
                    "source_role_mismatch",
                    "The source cannot be assigned to the requested role.",
                    status_code=422,
                )
            if not self._role_enabled(session, selected_role):
                raise ServiceError(
                    "source_role_disabled",
                    "The requested source role is disabled for this session.",
                    status_code=409,
                )
            self._bind_source(db, session, source, requested_mode="explicit")
            producer_epoch_id = str(source.sanitized_metadata.get("producer_epoch_id", "unknown"))
            epoch = self._ensure_epoch(db, session, source, producer_epoch_id)
            self._refresh_session_source_status(db, session)
            emit_ui_event(db, "session.state", session.id, self._session_payload(db, session))
            assert epoch is not None
            return epoch

    def selected_epoch(self, session_id: str, *, role: str) -> SourceEpochRecord | None:
        with self.database.transaction() as db:
            session = db.get(SessionRecord, session_id)
            if session is None:
                return None
            binding = self._active_binding(db, session_id, role)
            if binding is None or binding.source_id is None:
                return None
            return db.scalar(
                select(SourceEpochRecord)
                .where(
                    SourceEpochRecord.session_id == session_id,
                    SourceEpochRecord.binding_id == binding.id,
                    SourceEpochRecord.state.in_(("starting", "running")),
                )
                .order_by(SourceEpochRecord.started_at.desc())
            )

    async def finalize_epoch(
        self,
        epoch_id: str,
        *,
        reason: str,
        timeout_seconds: float = SOURCE_COMMAND_SECONDS,
    ) -> None:
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, epoch_id)
            if epoch is None or epoch.state == "stopped":
                return
            source = db.get(CaptureSourceRecord, epoch.source_id)
            if source is None or epoch.session_id is None or epoch.segment_id is None:
                epoch.state = "stopped"
                epoch.ended_at = utc_now()
                epoch.end_reason = reason
                return
            epoch.state = "stopping"
            client_id = source.paired_client_id
            payload = {
                "type": "source.stop",
                "protocol_version": 2,
                "source_id": source.id,
                "source_epoch_id": epoch.id,
                "tab_instance_id": source.tab_instance_id,
                "session_id": epoch.session_id,
                "segment_id": epoch.segment_id,
                "deadline_ms": int(timeout_seconds * 1000),
            }
        result = (
            await self.connections.command(
                client_id,
                payload,
                timeout_seconds=timeout_seconds,
            )
            if client_id is not None
            else {"result": "finalized"}
        )
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, epoch_id)
            if epoch is not None:
                epoch.state = "stopped"
                epoch.ended_at = utc_now()
                epoch.end_reason = (
                    reason
                    if result.get("result") == "finalized"
                    else str(result.get("error_code") or "producer_error")
                )

    async def start_epoch(self, epoch_id: str) -> str:
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, epoch_id)
            if epoch is None:
                return "source_not_bound"
            source = db.get(CaptureSourceRecord, epoch.source_id)
            if source is None or epoch.session_id is None or epoch.segment_id is None:
                return "source_not_bound"
            payload = {
                "type": "source.start",
                "protocol_version": 2,
                "source_id": source.id,
                "source_epoch_id": epoch.id,
                "tab_instance_id": source.tab_instance_id,
                "session_id": epoch.session_id,
                "segment_id": epoch.segment_id,
                "deadline_ms": int(SOURCE_COMMAND_SECONDS * 1000),
            }
            client_id = source.paired_client_id
        result = (
            await self.connections.command(
                client_id, payload, timeout_seconds=SOURCE_COMMAND_SECONDS
            )
            if client_id is not None
            else {"result": "started"}
        )
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, epoch_id)
            if epoch is not None and epoch.state == "starting":
                if result.get("result") == "started":
                    epoch.state = "running"
                else:
                    epoch.state = "failed"
                    epoch.end_reason = str(result.get("error_code") or "producer_error")
                    epoch.ended_at = utc_now()
                    session = db.get(SessionRecord, epoch.session_id) if epoch.session_id else None
                    binding = db.get(SessionSourceBindingRecord, epoch.binding_id)
                    if session is not None and binding is not None:
                        binding.state = "degraded"
                        binding.reason = epoch.end_reason
                        self._refresh_session_source_status(db, session)
                        emit_ui_event(
                            db, "session.state", session.id, self._session_payload(db, session)
                        )
        return str(result.get("result", "failed"))

    async def finalize_session(self, session_id: str, *, hard_budget_seconds: float) -> None:
        with self.database.transaction() as db:
            epochs = list(
                db.scalars(
                    select(SourceEpochRecord).where(
                        SourceEpochRecord.session_id == session_id,
                        SourceEpochRecord.state.in_(("starting", "running")),
                    )
                )
            )
            commands: list[tuple[str, str | None, dict[str, Any]]] = []
            for epoch in epochs:
                source = db.get(CaptureSourceRecord, epoch.source_id)
                if source is None or epoch.segment_id is None:
                    continue
                epoch.state = "stopping"
                commands.append(
                    (
                        epoch.id,
                        source.paired_client_id,
                        {
                            "type": "source.stop",
                            "protocol_version": 2,
                            "source_id": source.id,
                            "source_epoch_id": epoch.id,
                            "tab_instance_id": source.tab_instance_id,
                            "session_id": session_id,
                            "segment_id": epoch.segment_id,
                            "deadline_ms": int(SOURCE_COMMAND_SECONDS * 1000),
                        },
                    )
                )

        async def finalize(
            item: tuple[str, str | None, dict[str, Any]],
        ) -> tuple[str, dict[str, Any]]:
            epoch_id, client_id, payload = item
            result = (
                await self.connections.command(
                    client_id,
                    payload,
                    timeout_seconds=min(SOURCE_COMMAND_SECONDS, hard_budget_seconds),
                )
                if client_id is not None
                else {"result": "finalized"}
            )
            return epoch_id, result

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(finalize(item) for item in commands)),
                timeout=hard_budget_seconds,
            )
        except TimeoutError:
            results = []
        completed = {epoch_id: result for epoch_id, result in results}
        ended_at = utc_now()
        with self.database.transaction() as db:
            for epoch in db.scalars(
                select(SourceEpochRecord).where(
                    SourceEpochRecord.session_id == session_id,
                    SourceEpochRecord.state.in_(("starting", "running", "stopping")),
                )
            ):
                result = completed.get(epoch.id)
                epoch.state = "stopped"
                epoch.ended_at = ended_at
                epoch.end_reason = (
                    "finalized"
                    if result is not None and result.get("result") == "finalized"
                    else str((result or {}).get("error_code") or "finalize_timeout")
                )

    def disconnect_client(self, client_id: str) -> None:
        now = utc_now()
        with self.database.transaction() as db:
            for source in db.scalars(
                select(CaptureSourceRecord).where(
                    CaptureSourceRecord.paired_client_id == client_id,
                    CaptureSourceRecord.connected.is_(True),
                )
            ):
                source.connected = False
                source.health_status = "unavailable"
                source.last_error_code = "producer_disconnected"
                running = db.scalar(
                    select(SessionRecord).where(SessionRecord.recording_status == "running")
                )
                binding = (
                    self._active_binding_for_source(db, running.id, source.id)
                    if running is not None
                    else None
                )
                if binding is not None:
                    binding.state = "waiting"
                    binding.effective_mode = "unavailable"
                    binding.reason = "producer_disconnected"
                for epoch in db.scalars(
                    select(SourceEpochRecord).where(
                        SourceEpochRecord.source_id == source.id,
                        SourceEpochRecord.state.in_(("starting", "running")),
                    )
                ):
                    epoch.last_seen_at = now
                    epoch.last_health_status = "unavailable"
                    epoch.last_error_code = "producer_disconnected"
                emit_ui_event(db, "source.changed", source.id, self._source_payload(db, source))
                if running is not None and binding is not None:
                    self._refresh_session_source_status(db, running)
                    emit_ui_event(
                        db, "session.state", running.id, self._session_payload(db, running)
                    )

    @staticmethod
    def _live_candidates(db: Session, *, role: str) -> list[CaptureSourceRecord]:
        return list(
            db.scalars(
                select(CaptureSourceRecord).where(
                    CaptureSourceRecord.source_role == role,
                    CaptureSourceRecord.connected.is_(True),
                    CaptureSourceRecord.available.is_(True),
                    CaptureSourceRecord.health_status != "unavailable",
                )
            )
        )

    @staticmethod
    def _active_binding(
        db: Session, session_id: str, role: str
    ) -> SessionSourceBindingRecord | None:
        return db.scalar(
            select(SessionSourceBindingRecord)
            .where(
                SessionSourceBindingRecord.session_id == session_id,
                SessionSourceBindingRecord.role == role,
                SessionSourceBindingRecord.state.in_(ACTIVE_BINDING_STATES),
            )
            .order_by(SessionSourceBindingRecord.created_at.desc())
        )

    @staticmethod
    def _active_binding_for_source(
        db: Session, session_id: str, source_id: str
    ) -> SessionSourceBindingRecord | None:
        return db.scalar(
            select(SessionSourceBindingRecord).where(
                SessionSourceBindingRecord.session_id == session_id,
                SessionSourceBindingRecord.source_id == source_id,
                SessionSourceBindingRecord.state.in_(ACTIVE_BINDING_STATES),
            )
        )

    @classmethod
    def _ensure_waiting_binding(
        cls, db: Session, session: SessionRecord, role: str
    ) -> SessionSourceBindingRecord:
        current = cls._active_binding(db, session.id, role)
        if current is not None:
            return current
        segment = db.scalar(
            select(RecordingSegmentRecord)
            .where(
                RecordingSegmentRecord.session_id == session.id,
                RecordingSegmentRecord.stopped_at.is_(None),
            )
            .order_by(RecordingSegmentRecord.sequence.desc())
        )
        binding = SessionSourceBindingRecord(
            session_id=session.id,
            segment_id=segment.id if segment else None,
            role=role,
            requested_mode="auto",
            effective_mode="unavailable",
            state="waiting",
            reason="source_unavailable",
        )
        db.add(binding)
        db.flush()
        return binding

    @staticmethod
    def _ensure_disabled_binding(
        db: Session, session: SessionRecord, role: str
    ) -> SessionSourceBindingRecord:
        segment = db.scalar(
            select(RecordingSegmentRecord)
            .where(
                RecordingSegmentRecord.session_id == session.id,
                RecordingSegmentRecord.stopped_at.is_(None),
            )
            .order_by(RecordingSegmentRecord.sequence.desc())
        )
        current = db.scalar(
            select(SessionSourceBindingRecord).where(
                SessionSourceBindingRecord.session_id == session.id,
                SessionSourceBindingRecord.segment_id == (segment.id if segment else None),
                SessionSourceBindingRecord.role == role,
                SessionSourceBindingRecord.state == "disabled_by_user",
            )
        )
        if current is not None:
            return current
        binding = SessionSourceBindingRecord(
            session_id=session.id,
            segment_id=segment.id if segment else None,
            role=role,
            requested_mode="disabled",
            effective_mode="disabled",
            state="disabled_by_user",
            reason="disabled_by_user",
        )
        db.add(binding)
        db.flush()
        return binding

    @staticmethod
    def _role_enabled(session: SessionRecord, role: str) -> bool:
        if role == "self":
            return session.self_audio_enabled
        if role == "remote":
            return session.remote_audio_enabled
        return session.secondary_fallback_enabled

    @classmethod
    def _bind_source(
        cls,
        db: Session,
        session: SessionRecord,
        source: CaptureSourceRecord,
        *,
        requested_mode: str,
    ) -> SessionSourceBindingRecord:
        binding = cls._ensure_waiting_binding(db, session, source.source_role)
        binding.source_id = source.id
        binding.requested_mode = requested_mode
        binding.effective_mode = cls._effective_mode(source)
        binding.state = cls._binding_state(source)
        binding.reason = source.last_error_code
        binding.activated_at = binding.activated_at or utc_now()
        binding.updated_at = utc_now()
        return binding

    @classmethod
    def _ensure_epoch(
        cls,
        db: Session,
        session: SessionRecord | None,
        source: CaptureSourceRecord,
        producer_epoch_id: str,
    ) -> SourceEpochRecord | None:
        if session is None:
            return None
        binding = cls._active_binding_for_source(db, session.id, source.id)
        if binding is None:
            return None
        current = db.scalar(
            select(SourceEpochRecord).where(
                SourceEpochRecord.source_id == source.id,
                SourceEpochRecord.session_id == session.id,
                SourceEpochRecord.state.in_(("starting", "running")),
            )
        )
        if current is not None and current.producer_epoch_id == producer_epoch_id:
            return current
        now = utc_now()
        if current is not None:
            current.state = "stopped"
            current.ended_at = now
            current.end_reason = "producer_restart"
            current.producer_restart_count += 1
        segment = db.scalar(
            select(RecordingSegmentRecord)
            .where(
                RecordingSegmentRecord.session_id == session.id,
                RecordingSegmentRecord.stopped_at.is_(None),
            )
            .order_by(RecordingSegmentRecord.sequence.desc())
        )
        if segment is None:
            return None
        epoch = SourceEpochRecord(
            source_id=source.id,
            binding_id=binding.id,
            session_id=session.id,
            segment_id=segment.id,
            producer_epoch_id=producer_epoch_id,
            session_offset_base_us=(
                max(0, (monotonic_ns() - session.monotonic_origin_ns) // 1_000)
                if session.monotonic_origin_ns is not None
                else 0
            ),
            state="starting",
            started_at=now,
            last_seen_at=now,
            last_health_status=source.health_status,
        )
        db.add(epoch)
        db.flush()
        return epoch

    @staticmethod
    def _binding_state(source: CaptureSourceRecord) -> str:
        if not source.connected or not source.available:
            return "waiting"
        if source.health_status in {"degraded", "failed"}:
            return "degraded"
        if source.health_status == "waiting":
            return "waiting"
        return "active"

    @staticmethod
    def _effective_mode(source: CaptureSourceRecord) -> str:
        if source.source_kind == "browser_captions":
            return "captions"
        if source.source_kind == "synthetic_audio":
            return "synthetic"
        return "native"

    @staticmethod
    def _refresh_session_source_status(db: Session, session: SessionRecord) -> None:
        bindings = list(
            db.scalars(
                select(SessionSourceBindingRecord).where(
                    SessionSourceBindingRecord.session_id == session.id,
                    SessionSourceBindingRecord.state.in_(ACTIVE_BINDING_STATES),
                )
            )
        )
        if any(binding.state in {"degraded", "failed"} for binding in bindings):
            session.source_status = "degraded"
        elif any(binding.state == "active" for binding in bindings):
            session.source_status = "capturing"
        elif any(
            binding.role == "secondary" and binding.source_id is not None for binding in bindings
        ):
            session.source_status = "captions_not_detected"
        else:
            session.source_status = "waiting_for_source"

    @classmethod
    def _source_payload(
        cls,
        db: Session,
        source: CaptureSourceRecord,
        epoch: SourceEpochRecord | None = None,
    ) -> dict[str, object]:
        client = (
            db.get(PairedClientRecord, source.paired_client_id)
            if source.paired_client_id is not None
            else None
        )
        source_ids = (
            list(
                db.scalars(
                    select(CaptureSourceRecord.id)
                    .where(CaptureSourceRecord.paired_client_id == source.paired_client_id)
                    .order_by(CaptureSourceRecord.created_at, CaptureSourceRecord.id)
                )
            )
            if source.paired_client_id is not None
            else [source.id]
        )
        return cls.source_payload(
            source,
            epoch,
            client_display_name=client.display_name if client else None,
            browser_family=client.browser_family if client else None,
            tab_ordinal=source_ids.index(source.id) + 1,
        )

    @staticmethod
    def source_payload(
        source: CaptureSourceRecord,
        epoch: SourceEpochRecord | None = None,
        *,
        client_display_name: str | None = None,
        browser_family: str | None = None,
        tab_ordinal: int | None = None,
    ) -> dict[str, object]:
        return {
            "id": source.id,
            "paired_client_id": source.paired_client_id,
            "source_kind": source.source_kind,
            "source_category": source.source_category,
            "source_role": source.source_role,
            "target_key": source.target_key,
            "platform": source.platform,
            "driver_id": source.driver_id,
            "driver_version": source.driver_version,
            "protocol_version": source.protocol_version,
            "tab_instance_id": source.tab_instance_id,
            "capabilities": source.capabilities,
            "available": source.available,
            "connected": source.connected,
            "health_status": source.health_status,
            "last_error_code": source.last_error_code,
            "last_event_at": source.last_event_at.isoformat() if source.last_event_at else None,
            "source_epoch_id": epoch.id if epoch else None,
            "client_display_name": client_display_name,
            "browser_family": browser_family,
            "tab_ordinal": tab_ordinal,
        }

    @staticmethod
    def _session_payload(db: Session, session: SessionRecord) -> dict[str, object]:
        from elsewise.services.sessions import session_payload

        bindings = db.scalars(
            select(SessionSourceBindingRecord).where(
                SessionSourceBindingRecord.session_id == session.id,
                SessionSourceBindingRecord.state.in_((*ACTIVE_BINDING_STATES, "disabled_by_user")),
            )
        )
        return session_payload(session, bindings)

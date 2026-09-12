import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from sqlalchemy import func, select

from elsewise.persistence.database import Database
from elsewise.persistence.models import PairedClientRecord, PairingRequestRecord, utc_now
from elsewise.services.errors import ServiceError
from elsewise.services.outbox import emit_ui_event

PAIRING_TTL_SECONDS = 120
MAX_PENDING_PAIRING_REQUESTS = 32
LAST_SEEN_WRITE_INTERVAL_SECONDS = 30
_LABEL_RE = re.compile(r"[^\w .()\-]", re.UNICODE)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def sanitize_display_name(value: str) -> str:
    normalized = " ".join(value.strip().split())[:128]
    sanitized = _LABEL_RE.sub("", normalized)
    return sanitized or "Browser extension"


@dataclass(frozen=True, slots=True)
class PairingDelivery:
    client_id: str
    credential: str


class PairingService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._deliveries: dict[str, PairingDelivery] = {}
        self._lock = RLock()

    def expire_pending(self) -> None:
        now = utc_now()
        with self.database.transaction() as db:
            for request in db.scalars(
                select(PairingRequestRecord).where(PairingRequestRecord.state == "pending")
            ):
                request.state = "expired"
                request.decided_at = now

    def create_request(
        self,
        *,
        installation_id: str,
        browser_family: str,
        display_name: str,
        extension_version: str,
        nonce: str,
    ) -> PairingRequestRecord:
        if len(nonce) < 32:
            raise ServiceError(
                "invalid_pairing_nonce", "Pairing nonce is too short.", status_code=422
            )
        now = utc_now()
        with self.database.transaction() as db:
            existing = db.scalar(
                select(PairingRequestRecord).where(
                    PairingRequestRecord.installation_id == installation_id,
                    PairingRequestRecord.state == "pending",
                )
            )
            if existing is not None:
                if hmac.compare_digest(existing.nonce_digest, _digest(nonce)):
                    return existing
                existing.state = "cancelled"
                existing.decided_at = now
            pending_count = (
                db.scalar(
                    select(func.count(PairingRequestRecord.id)).where(
                        PairingRequestRecord.state == "pending"
                    )
                )
                or 0
            )
            if pending_count >= MAX_PENDING_PAIRING_REQUESTS:
                raise ServiceError(
                    "pairing_rate_limited",
                    "Too many pairing requests are pending.",
                    status_code=429,
                )
            request = PairingRequestRecord(
                installation_id=installation_id,
                browser_family=browser_family[:32],
                display_name=sanitize_display_name(display_name),
                extension_version=extension_version[:64],
                nonce_digest=_digest(nonce),
                created_at=now,
                expires_at=now + timedelta(seconds=PAIRING_TTL_SECONDS),
            )
            db.add(request)
            db.flush()
            emit_ui_event(db, "pairing.requested", request.id, self.request_payload(request))
            return request

    def list_requests(self) -> list[PairingRequestRecord]:
        self.expire_due()
        with self.database.transaction() as db:
            return list(
                db.scalars(
                    select(PairingRequestRecord)
                    .where(PairingRequestRecord.state == "pending")
                    .order_by(PairingRequestRecord.created_at)
                )
            )

    def list_clients(self) -> list[PairedClientRecord]:
        with self.database.transaction() as db:
            return list(
                db.scalars(select(PairedClientRecord).order_by(PairedClientRecord.created_at))
            )

    def approve(self, request_id: str) -> PairedClientRecord:
        with self._lock:
            self.expire_due()
        with self._lock, self.database.transaction() as db:
            request = db.get(PairingRequestRecord, request_id)
            self._require_pending(request)
            assert request is not None
            secret = secrets.token_urlsafe(32)
            client = db.scalar(
                select(PairedClientRecord).where(
                    PairedClientRecord.installation_id == request.installation_id
                )
            )
            if client is None:
                client = PairedClientRecord(
                    installation_id=request.installation_id,
                    browser_family=request.browser_family,
                    display_name=request.display_name,
                    credential_digest=_digest(secret),
                )
                db.add(client)
                db.flush()
            else:
                client.browser_family = request.browser_family
                client.display_name = request.display_name
                client.credential_digest = _digest(secret)
                client.status = "active"
                client.revoked_at = None
            request.state = "approved"
            request.decided_at = utc_now()
            credential = f"{client.id}.{secret}"
            self._deliveries[request.id] = PairingDelivery(client.id, credential)
            emit_ui_event(db, "pairing.changed", client.id, self.client_payload(client))
            return client

    def decide(self, request_id: str, state: str) -> PairingRequestRecord:
        if state not in {"denied", "cancelled"}:
            raise ValueError(state)
        with self._lock:
            self.expire_due()
        with self._lock, self.database.transaction() as db:
            request = db.get(PairingRequestRecord, request_id)
            self._require_pending(request)
            assert request is not None
            request.state = state
            request.decided_at = utc_now()
            emit_ui_event(db, "pairing.changed", request.id, self.request_payload(request))
            return request

    def take_delivery(self, request_id: str, nonce: str) -> PairingDelivery | None:
        with self._lock, self.database.transaction() as db:
            request = db.get(PairingRequestRecord, request_id)
            if request is None or not hmac.compare_digest(request.nonce_digest, _digest(nonce)):
                raise ServiceError(
                    "invalid_pairing_nonce", "Pairing proof is invalid.", status_code=403
                )
            if _aware(request.expires_at) <= utc_now():
                return None
            return self._deliveries.pop(request_id, None)

    def request_state(self, request_id: str, nonce: str) -> str:
        self.expire_due()
        with self.database.transaction() as db:
            request = db.get(PairingRequestRecord, request_id)
            if request is None or not hmac.compare_digest(request.nonce_digest, _digest(nonce)):
                raise ServiceError(
                    "invalid_pairing_nonce", "Pairing proof is invalid.", status_code=403
                )
            return request.state

    def verify(self, credential: str) -> PairedClientRecord | None:
        try:
            client_id, secret = credential.split(".", 1)
        except ValueError:
            return None
        with self.database.transaction() as db:
            client = db.get(PairedClientRecord, client_id)
            if client is None or client.status != "active":
                return None
            if not hmac.compare_digest(client.credential_digest, _digest(secret)):
                return None
            now = utc_now()
            if (
                client.last_seen_at is None
                or (now - _aware(client.last_seen_at)).total_seconds()
                >= LAST_SEEN_WRITE_INTERVAL_SECONDS
            ):
                client.last_seen_at = now
            return client

    def rename(self, client_id: str, display_name: str) -> PairedClientRecord:
        with self.database.transaction() as db:
            client = db.get(PairedClientRecord, client_id)
            if client is None:
                raise ServiceError(
                    "paired_client_not_found", "Paired client not found.", status_code=404
                )
            client.display_name = sanitize_display_name(display_name)
            emit_ui_event(db, "pairing.changed", client.id, self.client_payload(client))
            return client

    def revoke(self, client_id: str) -> PairedClientRecord:
        with self.database.transaction() as db:
            client = db.get(PairedClientRecord, client_id)
            if client is None:
                raise ServiceError(
                    "paired_client_not_found", "Paired client not found.", status_code=404
                )
            client.status = "revoked"
            client.revoked_at = utc_now()
            emit_ui_event(db, "pairing.changed", client.id, self.client_payload(client))
            return client

    def expire_due(self) -> None:
        now = utc_now()
        expired_ids: list[str] = []
        with self.database.transaction() as db:
            for request in db.scalars(
                select(PairingRequestRecord).where(
                    PairingRequestRecord.state == "pending",
                    PairingRequestRecord.expires_at <= now,
                )
            ):
                request.state = "expired"
                request.decided_at = now
                expired_ids.append(request.id)
        with self._lock:
            for request_id in expired_ids:
                self._deliveries.pop(request_id, None)

    @staticmethod
    def _require_pending(request: PairingRequestRecord | None) -> None:
        if request is None:
            raise ServiceError(
                "pairing_request_not_found", "Pairing request not found.", status_code=404
            )
        if request.state != "pending":
            raise ServiceError(
                "pairing_request_already_decided",
                "Pairing request is no longer pending.",
                status_code=409,
            )

    @staticmethod
    def request_payload(request: PairingRequestRecord) -> dict[str, object]:
        return {
            "id": request.id,
            "installation_id": request.installation_id,
            "browser_family": request.browser_family,
            "display_name": request.display_name,
            "extension_version": request.extension_version,
            "state": request.state,
            "created_at": request.created_at.isoformat(),
            "expires_at": request.expires_at.isoformat(),
        }

    @staticmethod
    def client_payload(client: PairedClientRecord) -> dict[str, object]:
        return {
            "id": client.id,
            "installation_id": client.installation_id,
            "browser_family": client.browser_family,
            "display_name": client.display_name,
            "status": client.status,
            "created_at": client.created_at.isoformat(),
            "last_seen_at": client.last_seen_at.isoformat() if client.last_seen_at else None,
            "revoked_at": client.revoked_at.isoformat() if client.revoked_at else None,
        }

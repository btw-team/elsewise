from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from elsewise.persistence.database import Database
from elsewise.persistence.models import PairedClientRecord, PairingRequestRecord, utc_now
from elsewise.services.errors import ServiceError
from elsewise.services.pairing import PairingService
from sqlalchemy import select


def service(tmp_path: Path) -> tuple[Database, PairingService]:
    database = Database.from_path(tmp_path / "pairing.sqlite3")
    database.create_schema()
    return database, PairingService(database)


def test_pairing_persists_only_digest_and_delivery_is_one_time(tmp_path: Path) -> None:
    database, pairing = service(tmp_path)
    nonce = "n" * 64
    request = pairing.create_request(
        installation_id=str(uuid4()),
        browser_family="chrome",
        display_name=" Work <Chrome> ",
        extension_version="2.0.0",
        nonce=nonce,
    )
    client = pairing.approve(request.id)
    delivery = pairing.take_delivery(request.id, nonce)
    assert delivery is not None
    assert delivery.client_id == client.id
    assert pairing.take_delivery(request.id, nonce) is None
    assert pairing.verify(delivery.credential) is not None
    with database.transaction() as db:
        stored = db.get(PairedClientRecord, client.id)
        assert stored is not None
        assert delivery.credential not in stored.credential_digest
        assert stored.display_name == "Work Chrome"
    database.dispose()


def test_pairing_reconnect_cancel_expiry_and_wrong_nonce(tmp_path: Path) -> None:
    database, pairing = service(tmp_path)
    installation_id = str(uuid4())
    nonce = "r" * 64
    first = pairing.create_request(
        installation_id=installation_id,
        browser_family="firefox",
        display_name="Firefox",
        extension_version="2.0.0",
        nonce=nonce,
    )
    assert (
        pairing.create_request(
            installation_id=installation_id,
            browser_family="firefox",
            display_name="Firefox",
            extension_version="2.0.0",
            nonce=nonce,
        ).id
        == first.id
    )
    with pytest.raises(ServiceError, match="proof"):
        pairing.request_state(first.id, "x" * 64)
    pairing.decide(first.id, "cancelled")
    assert pairing.request_state(first.id, nonce) == "cancelled"

    expiring = pairing.create_request(
        installation_id=str(uuid4()),
        browser_family="chrome",
        display_name="Chrome",
        extension_version="2.0.0",
        nonce="e" * 64,
    )
    with database.transaction() as db:
        record = db.get(PairingRequestRecord, expiring.id)
        assert record is not None
        record.expires_at = utc_now() - timedelta(seconds=1)
    pairing.expire_due()
    assert pairing.request_state(expiring.id, "e" * 64) == "expired"
    database.dispose()


def test_repair_rotates_one_client_and_revoke_does_not_touch_another(tmp_path: Path) -> None:
    database, pairing = service(tmp_path)
    credentials: list[str] = []
    clients: list[str] = []
    installations = [str(uuid4()), str(uuid4())]
    for index, installation_id in enumerate(installations):
        nonce = str(index) * 64
        request = pairing.create_request(
            installation_id=installation_id,
            browser_family="chrome",
            display_name=f"Chrome {index}",
            extension_version="2.0.0",
            nonce=nonce,
        )
        client = pairing.approve(request.id)
        delivery = pairing.take_delivery(request.id, nonce)
        assert delivery is not None
        clients.append(client.id)
        credentials.append(delivery.credential)
    pairing.revoke(clients[0])
    assert pairing.verify(credentials[0]) is None
    assert pairing.verify(credentials[1]) is not None
    with database.transaction() as db:
        assert len(list(db.scalars(select(PairedClientRecord)))) == 2
    database.dispose()

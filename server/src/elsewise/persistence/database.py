from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from elsewise.persistence.models import Base


def _configure_sqlite(connection: object, _: object) -> None:
    cursor = connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        options: dict[str, object] = {"check_same_thread": False}
        engine_options: dict[str, object] = {"connect_args": options}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            engine_options["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **engine_options)
        event.listen(self.engine, "connect", _configure_sqlite)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.transition_lock = RLock()

    @classmethod
    def from_path(cls, path: Path) -> "Database":
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(f"sqlite:///{path}")

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def migrate(self) -> None:
        if self.url in {"sqlite://", "sqlite:///:memory:"}:
            self.create_schema()
            return
        migrations_root = Path(__file__).resolve().parents[1] / "migrations"
        config = Config()
        config.set_main_option("script_location", str(migrations_root))
        config.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        command.upgrade(config, "head")

    def dispose(self) -> None:
        self.engine.dispose()

    def vacuum(self) -> None:
        if self.url in {"sqlite://", "sqlite:///:memory:"}:
            return
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.exec_driver_sql("VACUUM")

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.session_factory.begin() as session:
            yield session

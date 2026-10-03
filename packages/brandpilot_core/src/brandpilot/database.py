"""Database engine and session construction."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text
import re

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str, *, role: str | None = None) -> Engine:
    options: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    engine = create_engine(database_url, **options)
    if role and engine.dialect.name == "postgresql":
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
            raise ValueError("Database role name is invalid")

        @event.listens_for(engine, "connect")
        def assume_application_role(dbapi_connection, _connection_record) -> None:
            with dbapi_connection.cursor() as cursor:
                cursor.execute(f'SET ROLE "{role}"')

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def set_workspace_context(session: Session, workspace_id: str) -> None:
    """Set transaction-local PostgreSQL context consumed by RLS policies."""
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": workspace_id},
        )


@contextmanager
def workspace_transaction(
    sessions: sessionmaker[Session], workspace_id: str
):
    if not workspace_id:
        raise ValueError("workspace_id is required")
    with sessions() as session, session.begin():
        set_workspace_context(session, workspace_id)
        yield session

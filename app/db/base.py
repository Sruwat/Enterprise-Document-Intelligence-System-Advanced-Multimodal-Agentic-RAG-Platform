from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)
_current_workspace_id: ContextVar[str | None] = ContextVar("current_workspace_id", default=None)


def build_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    return create_engine(url, pool_pre_ping=True, future=True)


def build_session_factory(database_url: str | None = None):
    return sessionmaker(bind=build_engine(database_url), autoflush=False, autocommit=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    factory = build_session_factory(database_url)
    session = factory()
    try:
        _apply_rls_context(session)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def tenant_context(tenant_id: str | None = None, workspace_id: str | None = None):
    tenant_token = _current_tenant_id.set(tenant_id)
    workspace_token = _current_workspace_id.set(workspace_id)
    try:
        yield
    finally:
        _current_workspace_id.reset(workspace_token)
        _current_tenant_id.reset(tenant_token)


def _apply_rls_context(session: Session) -> None:
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    tenant_id = _current_tenant_id.get()
    workspace_id = _current_workspace_id.get()
    if tenant_id:
        session.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    if workspace_id:
        session.execute(text("SET LOCAL app.current_workspace_id = :workspace_id"), {"workspace_id": workspace_id})


def set_rls_context(tenant_id: str | None = None, workspace_id: str | None = None) -> None:
    if tenant_id is not None:
        _current_tenant_id.set(tenant_id)
    if workspace_id is not None:
        _current_workspace_id.set(workspace_id)

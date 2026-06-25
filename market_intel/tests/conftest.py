import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base


@pytest.fixture
def session():
    """A fresh in-memory SQLite database per test, schema created directly from
    the models (bypasses Alembic for speed -- fine for unit tests).

    StaticPool + check_same_thread=False is required here: FastAPI's TestClient
    runs requests on a different thread, and a plain sqlite://:memory:engine
    hands out a brand-new, empty in-memory database per connection -- without a
    single shared connection, table-creation and queries land on different
    databases and every query fails with "no such table".
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def client(session):
    """FastAPI TestClient with the get_db dependency overridden to use the
    in-memory test session instead of the real database."""
    from fastapi.testclient import TestClient

    from api.main import app
    from db.session import get_db

    def override_get_db():
        yield session
        session.commit()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()

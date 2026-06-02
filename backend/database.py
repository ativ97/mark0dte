from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timezone

SQLALCHEMY_DATABASE_URL = "sqlite:///./quant_engine.db"

# Initialize SQLite engine (check_same_thread=False is required for FastAPI)
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class PositionDB(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, index=True)  # 'Put Spread', 'Call Spread', 'Iron Condor'
    strike = Column(Float)
    credit = Column(Float)
    contracts = Column(Integer, default=1)  # P0-3: position size, for account-level risk sizing
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # PHASE 3: This tracks the exact second a Gamma Trap boundary is breached
    breach_start_time = Column(DateTime, nullable=True)


class ClosedPositionDB(Base):
    __tablename__ = "closed_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_id = Column(Integer, index=True)
    type = Column(String)
    strike = Column(Float)
    credit = Column(Float)
    opened_at = Column(DateTime)
    closed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    close_reason = Column(String, default="manual")  # manual, eject, expired
    close_price = Column(Float, nullable=True)  # What the position was closed at
    realized_pl = Column(Float, nullable=True)  # credit - close_price (per contract)


def _ensure_schema():
    """Idempotent schema guard (P0-3). SQLite `create_all` does NOT ALTER existing tables
    (see CLAUDE.md DB pitfall), so add columns introduced after the DB already exists."""
    try:
        Base.metadata.create_all(bind=engine)
        with engine.connect() as conn:
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(positions)").fetchall()]
            if "contracts" not in cols:
                conn.exec_driver_sql("ALTER TABLE positions ADD COLUMN contracts INTEGER DEFAULT 1")
                conn.commit()
    except Exception as e:  # never block startup on a migration hiccup
        import logging
        logging.getLogger("0DTE-QuantEngine").warning(f"_ensure_schema migration skipped: {e}")


# Run the guard on import so an existing quant_engine.db gains the `contracts` column.
_ensure_schema()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
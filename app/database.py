from sqlalchemy import create_engine, QueuePool
from sqlalchemy.orm import sessionmaker

engine = create_engine(
    "sqlite:///./app.db",
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///finances.db")

if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    if not os.path.isabs(db_path):
        db_path = str(Path.cwd() / db_path)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)


SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    return SessionLocal()

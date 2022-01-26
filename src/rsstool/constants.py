import pathlib
import os
import uuid

DB_LOC = os.getenv("DB_LOC", None)
if DB_LOC is None:
    parent = pathlib.Path(__file__).parent.parent.parent.absolute()
    DB_LOC = parent / "rss.db"


MODELS_LOC = os.getenv("RSS_MODELS_LOC", None)
if MODELS_LOC is None:
    parent = pathlib.Path(__file__).parent.parent.parent.absolute()
    MODELS_LOC = parent / "models"

USERNAME = os.getenv("RSS_USERNAME", uuid.uuid4())
PASSWORD = os.getenv("RSS_PASSWORD", uuid.uuid4())

"""Session metadata and append-only recording files."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def default_data_dir() -> Path:
    return Path(os.environ.get("ENGAGELAB_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))


class SessionStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else default_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, session_id: str) -> Path:
        if str(UUID(session_id)) != session_id:
            raise ValueError("Invalid session ID")
        return self.root / session_id

    def create(self, name: str, game: str = "") -> dict:
        if not name.strip():
            raise ValueError("Session name cannot be empty")
        session = {
            "schema_version": 1,
            "id": str(uuid4()),
            "name": name.strip(),
            "game": game.strip(),
            "created_at": utc_now(),
            "status": "created",
            "streams": [],
        }
        self.directory(session["id"]).mkdir()
        self.save(session)
        return session

    def save(self, session: dict) -> None:
        directory = self.directory(session["id"])
        temporary = directory / "session.json.tmp"
        temporary.write_text(json.dumps(session, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(directory / "session.json")

    def get(self, session_id: str) -> dict:
        return json.loads((self.directory(session_id) / "session.json").read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        sessions = []
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            try:
                sessions.append(self.get(directory.name))
            except (ValueError, OSError):
                continue
        return sorted(sessions, key=lambda session: session["created_at"], reverse=True)

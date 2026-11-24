"""Session metadata and append-only recording files."""

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4


def utc_now() -> str:
    """Return the current UTC wall-clock time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def default_data_dir() -> Path:
    """Use ENGAGELAB_DATA_DIR when set, otherwise use the project's data directory."""
    return Path(os.environ.get("ENGAGELAB_DATA_DIR", Path(__file__).resolve().parents[3] / "data"))


class SessionStore:
    """Manage session metadata and files in per-session UUID directories."""

    def __init__(self, root: Path | None = None):
        """Create the recording root if it does not exist."""
        self.root = Path(root) if root is not None else default_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, session_id: str) -> Path:
        """Build a session path from a canonical UUID, raising ValueError otherwise."""
        if str(UUID(session_id)) != session_id:
            raise ValueError("Invalid session ID")
        return self.root / session_id

    def create(self, name: str, game: str = "") -> dict:
        """Create a session directory and save its initial metadata."""
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
        """Write session metadata via a temporary file and atomically replace session.json."""
        directory = self.directory(session["id"])
        temporary = directory / "session.json.tmp"
        temporary.write_text(json.dumps(session, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(directory / "session.json")

    def get(self, session_id: str) -> dict:
        """Read session.json for the given session ID."""
        return json.loads((self.directory(session_id) / "session.json").read_text(encoding="utf-8"))

    def delete(self, session_id: str) -> None:
        """Delete a session and its files after checking the directory and metadata."""
        directory = self.directory(session_id)
        if directory.is_symlink() or directory.resolve().parent != self.root.resolve():
            raise ValueError("Session directory must be inside the recording data directory")
        self.get(session_id)
        shutil.rmtree(directory)

    def list(self) -> list[dict]:
        """Return readable session records with the newest creation date first."""
        sessions = []
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            try:
                sessions.append(self.get(directory.name))
            except (ValueError, OSError):
                continue
        return sorted(sessions, key=lambda session: session["created_at"], reverse=True)

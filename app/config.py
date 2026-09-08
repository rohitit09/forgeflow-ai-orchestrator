import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Load a .env / .ENV file into os.environ (only sets variables not already set)."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val


# Load .ENV from project root before anything else reads config
_load_env_file(BASE_DIR / ".ENV")


class Settings:
    def __init__(self, base_dir: Path | None = None, config_dir: Path | None = None, bugs_dir: Path | None = None):
        self._base_dir: Path   = base_dir or BASE_DIR
        self.config_dir: Path  = config_dir or (BASE_DIR / "config")
        self.bugs_dir: Path    = bugs_dir or (BASE_DIR / "bugs")
        self.workspace_dir: Path = BASE_DIR / "workspace"  # cloned repos live here
        self.host: str = "0.0.0.0"
        self.port: int = 8000
        self._init_derived()

    def _init_derived(self) -> None:
        # sessions.json — active sessions only; sessions_history.json — closed/completed
        self.sessions_file         = self._base_dir / "sessions.json"
        self.sessions_history_file = self._base_dir / "sessions_history.json"

        # config files
        self.repositories_config = self.config_dir / "repositories.json"
        self.agents_config       = self.config_dir / "agents.json"
        self.integrations_config = self.config_dir / "integrations.json"

    def _bootstrap(self) -> None:
        self.bugs_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        if not self.sessions_file.exists():
            self.sessions_file.write_text('{"sessions": []}', encoding="utf-8")
        if not self.sessions_history_file.exists():
            self.sessions_history_file.write_text('{"sessions": []}', encoding="utf-8")


settings = Settings()
settings._bootstrap()

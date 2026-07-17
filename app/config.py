import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("DPR_DATA_DIR")
    if override:
        path = Path(override)
    else:
        path = Path.home() / "Documents" / "DPR"
    path.mkdir(parents=True, exist_ok=True)
    (path / "backups").mkdir(exist_ok=True)
    (path / "exports").mkdir(exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "dpr.sqlite3"


def config_path() -> Path:
    return data_dir() / "config.json"


@dataclass
class Config:
    email_backup_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    last_email_sent_at: str = field(default="")


def load_config() -> Config:
    path = config_path()
    if not path.exists():
        cfg = Config()
        save_config(cfg)
        return cfg
    data = json.loads(path.read_text())
    return Config(**{**asdict(Config()), **data})


def save_config(cfg: Config) -> None:
    config_path().write_text(json.dumps(asdict(cfg), indent=2))

import shutil
from datetime import datetime

from app.config import data_dir, db_path

KEEP_LAST = 30


def backup_to_folder() -> str:
    backups_dir = data_dir() / "backups"
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    dest = backups_dir / f"dpr-{stamp}.db"
    shutil.copy2(db_path(), dest)

    existing = sorted(backups_dir.glob("dpr-*.db"))
    for stale in existing[:-KEEP_LAST]:
        stale.unlink()

    return str(dest)

import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app.config import Config, db_path, load_config, save_config
from app.exporter import export_workbook

SEND_INTERVAL_DAYS = 7


def due_for_send(cfg: Config) -> bool:
    if not cfg.email_backup_enabled:
        return False
    if not cfg.last_email_sent_at:
        return True
    last = datetime.fromisoformat(cfg.last_email_sent_at)
    return datetime.now(timezone.utc) - last >= timedelta(days=SEND_INTERVAL_DAYS)


def send_weekly_backup(conn, cfg: Config | None = None) -> bool:
    cfg = cfg or load_config()
    if not due_for_send(cfg):
        return False

    xlsx_buffer = export_workbook(conn)
    msg = EmailMessage()
    msg["Subject"] = f"DPR weekly backup — {datetime.now().date().isoformat()}"
    msg["From"] = cfg.smtp_from
    msg["To"] = cfg.smtp_to
    msg.set_content("Weekly DPR backup attached: export and full database.")
    msg.add_attachment(
        xlsx_buffer.read(),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="dpr-export.xlsx",
    )
    with open(db_path(), "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="x-sqlite3", filename="dpr.db")

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as smtp:
        smtp.starttls()
        if cfg.smtp_username:
            smtp.login(cfg.smtp_username, cfg.smtp_password)
        smtp.send_message(msg)

    cfg.last_email_sent_at = datetime.now(timezone.utc).isoformat()
    save_config(cfg)
    return True

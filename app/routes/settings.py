from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.backup import backup_to_folder
from app.config import Config, data_dir, load_config, save_config
from app.web import base_context, get_conn, templates

router = APIRouter()


def _redirect():
    return RedirectResponse(url="/settings", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_screen(request: Request, message: str = "", conn=Depends(get_conn)):
    stages = conn.execute("SELECT * FROM stages ORDER BY rank").fetchall()
    brands = conn.execute("SELECT * FROM brands ORDER BY name").fetchall()
    sub_brands = conn.execute(
        "SELECT sb.*, b.name AS brand_name FROM sub_brands sb JOIN brands b ON b.id = sb.brand_id "
        "ORDER BY b.name, sb.name"
    ).fetchall()
    users = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    cfg = load_config()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            **base_context(request, conn),
            "stages": stages,
            "brands": brands,
            "sub_brands": sub_brands,
            "users": users,
            "data_dir": str(data_dir()),
            "cfg": cfg,
            "message": message,
        },
    )


# --- Stages ---

@router.post("/settings/stages/add")
def add_stage(name: str = Form(...), conn=Depends(get_conn)):
    (max_rank,) = conn.execute("SELECT COALESCE(MAX(rank), 0) FROM stages").fetchone()
    conn.execute("INSERT INTO stages (name, rank) VALUES (?, ?)", (name, max_rank + 1))
    conn.commit()
    return _redirect()


@router.post("/settings/stages/{stage_id}/rename")
def rename_stage(stage_id: int, name: str = Form(...), conn=Depends(get_conn)):
    conn.execute("UPDATE stages SET name = ? WHERE id = ?", (name, stage_id))
    conn.commit()
    return _redirect()


@router.post("/settings/stages/{stage_id}/toggle-active")
def toggle_stage(stage_id: int, conn=Depends(get_conn)):
    conn.execute("UPDATE stages SET active = 1 - active WHERE id = ?", (stage_id,))
    conn.commit()
    return _redirect()


@router.post("/settings/stages/{stage_id}/move")
def move_stage(stage_id: int, direction: str = Form(...), conn=Depends(get_conn)):
    stage = conn.execute("SELECT * FROM stages WHERE id = ?", (stage_id,)).fetchone()
    if direction == "up":
        neighbor = conn.execute(
            "SELECT * FROM stages WHERE rank < ? ORDER BY rank DESC LIMIT 1", (stage["rank"],)
        ).fetchone()
    else:
        neighbor = conn.execute(
            "SELECT * FROM stages WHERE rank > ? ORDER BY rank ASC LIMIT 1", (stage["rank"],)
        ).fetchone()
    if neighbor:
        conn.execute("UPDATE stages SET rank = ? WHERE id = ?", (neighbor["rank"], stage["id"]))
        conn.execute("UPDATE stages SET rank = ? WHERE id = ?", (stage["rank"], neighbor["id"]))
        conn.commit()
    return _redirect()


# --- Brands ---

@router.post("/settings/brands/add")
def add_brand(name: str = Form(...), conn=Depends(get_conn)):
    conn.execute("INSERT INTO brands (name) VALUES (?)", (name,))
    conn.commit()
    return _redirect()


@router.post("/settings/brands/{brand_id}/rename")
def rename_brand(brand_id: int, name: str = Form(...), conn=Depends(get_conn)):
    conn.execute("UPDATE brands SET name = ? WHERE id = ?", (name, brand_id))
    conn.commit()
    return _redirect()


@router.post("/settings/brands/{brand_id}/toggle-active")
def toggle_brand(brand_id: int, conn=Depends(get_conn)):
    conn.execute("UPDATE brands SET active = 1 - active WHERE id = ?", (brand_id,))
    conn.commit()
    return _redirect()


# --- Sub-brands ---

@router.post("/settings/sub-brands/add")
def add_sub_brand(brand_id: int = Form(...), name: str = Form(...), conn=Depends(get_conn)):
    conn.execute("INSERT INTO sub_brands (brand_id, name) VALUES (?, ?)", (brand_id, name))
    conn.commit()
    return _redirect()


@router.post("/settings/sub-brands/{sub_brand_id}/rename")
def rename_sub_brand(sub_brand_id: int, name: str = Form(...), conn=Depends(get_conn)):
    conn.execute("UPDATE sub_brands SET name = ? WHERE id = ?", (name, sub_brand_id))
    conn.commit()
    return _redirect()


# --- Users ---

@router.post("/settings/users/add")
def add_user(name: str = Form(...), conn=Depends(get_conn)):
    conn.execute("INSERT INTO users (name) VALUES (?)", (name,))
    conn.commit()
    return _redirect()


@router.post("/settings/users/{user_id}/rename")
def rename_user(user_id: int, name: str = Form(...), conn=Depends(get_conn)):
    conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
    conn.commit()
    return _redirect()


@router.post("/settings/users/{user_id}/toggle-active")
def toggle_user(user_id: int, conn=Depends(get_conn)):
    conn.execute("UPDATE users SET active = 1 - active WHERE id = ?", (user_id,))
    conn.commit()
    return _redirect()


# --- Backup / email ---

@router.post("/settings/backup")
def do_backup(conn=Depends(get_conn)):
    backup_to_folder()
    return RedirectResponse(url="/settings?message=Backed+up.", status_code=303)


@router.post("/settings/email")
def save_email_config(
    email_backup_enabled: bool = Form(False),
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_username: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from: str = Form(""),
    smtp_to: str = Form(""),
):
    cfg = load_config()
    cfg.email_backup_enabled = email_backup_enabled
    cfg.smtp_host = smtp_host
    cfg.smtp_port = smtp_port
    cfg.smtp_username = smtp_username
    cfg.smtp_password = smtp_password
    cfg.smtp_from = smtp_from
    cfg.smtp_to = smtp_to
    save_config(cfg)
    return _redirect()

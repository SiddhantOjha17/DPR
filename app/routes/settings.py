from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.backup import backup_to_folder
from app.config import Config, data_dir, load_config, save_config
from app.web import base_context, get_conn, new_toast_id, require_permission, templates

router = APIRouter(dependencies=[Depends(require_permission("admin"))])


def _redirect(message: str = "", undo_url: str = "", undo_field: str = "", undo_value: str = "", error: str = ""):
    params = {"message": message}
    if error:
        params = {"message": "", "error": error}
    if undo_url:
        params["undo_url"] = undo_url
        params["undo_field"] = undo_field
        params["undo_value"] = undo_value
    return RedirectResponse(url=f"/settings?{urlencode(params)}", status_code=303)


def _admin_capable_user_count(conn, excluding_user_id: int | None = None) -> int:
    query = (
        "SELECT COUNT(*) FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE u.active = 1 AND r.active = 1 AND r.can_admin = 1"
    )
    params: list = []
    if excluding_user_id is not None:
        query += " AND u.id != ?"
        params.append(excluding_user_id)
    return conn.execute(query, params).fetchone()[0]


def _role_active_user_count(conn, role_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role_id = ? AND active = 1", (role_id,)
    ).fetchone()[0]


@router.get("/settings", response_class=HTMLResponse)
def settings_screen(
    request: Request,
    message: str = "",
    error: str = "",
    undo_url: str = "",
    undo_field: str = "",
    undo_value: str = "",
    conn=Depends(get_conn),
):
    stages = conn.execute("SELECT * FROM stages WHERE active = 1 ORDER BY rank, id").fetchall()
    brands = conn.execute("SELECT * FROM brands WHERE active = 1 ORDER BY name").fetchall()
    sub_brands = conn.execute(
        "SELECT sb.*, b.name AS brand_name FROM sub_brands sb JOIN brands b ON b.id = sb.brand_id "
        "WHERE b.active = 1 ORDER BY b.name, sb.name"
    ).fetchall()
    roles = conn.execute("SELECT * FROM roles WHERE active = 1 ORDER BY name").fetchall()
    users = conn.execute(
        "SELECT u.*, r.name AS role_name FROM users u LEFT JOIN roles r ON r.id = u.role_id "
        "WHERE u.active = 1 ORDER BY u.name"
    ).fetchall()
    cfg = load_config()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            **base_context(request, conn),
            "stages": stages,
            "brands": brands,
            "sub_brands": sub_brands,
            "roles": roles,
            "users": users,
            "data_dir": str(data_dir()),
            "cfg": cfg,
            "error_message": error,
            "toast_message": message,
            "toast_undo_url": undo_url,
            "toast_undo_fields": {undo_field: undo_value} if undo_field else {},
            "toast_undo_htmx": False,
            "toast_id": new_toast_id(),
        },
    )


# --- Stages ---

@router.post("/settings/stages/add")
def add_stage(name: str = Form(...), conn=Depends(get_conn)):
    (max_rank,) = conn.execute("SELECT COALESCE(MAX(rank), 0) FROM stages").fetchone()
    cur = conn.execute("INSERT INTO stages (name, rank) VALUES (?, ?)", (name, max_rank + 1))
    conn.commit()
    return _redirect(f"Added stage {name}.", undo_url=f"/settings/stages/{cur.lastrowid}/delete")


@router.post("/settings/stages/{stage_id}/rename")
def rename_stage(stage_id: int, name: str = Form(...), conn=Depends(get_conn)):
    old = conn.execute("SELECT name FROM stages WHERE id = ?", (stage_id,)).fetchone()
    conn.execute("UPDATE stages SET name = ? WHERE id = ?", (name, stage_id))
    conn.commit()
    return _redirect(
        "Renamed.", undo_url=f"/settings/stages/{stage_id}/rename", undo_field="name", undo_value=old["name"]
    )


@router.post("/settings/stages/{stage_id}/delete")
def delete_stage(stage_id: int, conn=Depends(get_conn)):
    stage = conn.execute("SELECT name FROM stages WHERE id = ?", (stage_id,)).fetchone()
    conn.execute("UPDATE stages SET active = 0 WHERE id = ?", (stage_id,))
    conn.commit()
    return _redirect(f"{stage['name']} removed.")


@router.post("/settings/stages/{stage_id}/move")
def move_stage(stage_id: int, direction: str = Form(...), conn=Depends(get_conn)):
    # Swapping stored rank *values* silently no-ops whenever two stages already
    # share a rank (real data has ties - see the STAGES-sheet import) - swapping
    # both to the same value changes nothing. Swap list *positions* instead and
    # renumber everyone to clean, unique 1..N ranks, so a click always produces
    # a visible move regardless of any pre-existing duplicate/gapped ranks.
    ids = [row["id"] for row in conn.execute("SELECT id FROM stages WHERE active = 1 ORDER BY rank, id")]
    index = ids.index(stage_id)
    neighbor_index = index - 1 if direction == "up" else index + 1
    if 0 <= neighbor_index < len(ids):
        ids[index], ids[neighbor_index] = ids[neighbor_index], ids[index]
    for position, id_ in enumerate(ids, start=1):
        conn.execute("UPDATE stages SET rank = ? WHERE id = ?", (position, id_))
    conn.commit()
    return _redirect()


# --- Brands ---

@router.post("/settings/brands/add")
def add_brand(name: str = Form(...), conn=Depends(get_conn)):
    cur = conn.execute("INSERT INTO brands (name) VALUES (?)", (name,))
    conn.commit()
    return _redirect(f"Added brand {name}.", undo_url=f"/settings/brands/{cur.lastrowid}/delete")


@router.post("/settings/brands/{brand_id}/rename")
def rename_brand(brand_id: int, name: str = Form(...), conn=Depends(get_conn)):
    old = conn.execute("SELECT name FROM brands WHERE id = ?", (brand_id,)).fetchone()
    conn.execute("UPDATE brands SET name = ? WHERE id = ?", (name, brand_id))
    conn.commit()
    return _redirect(
        "Renamed.", undo_url=f"/settings/brands/{brand_id}/rename", undo_field="name", undo_value=old["name"]
    )


@router.post("/settings/brands/{brand_id}/delete")
def delete_brand(brand_id: int, conn=Depends(get_conn)):
    brand = conn.execute("SELECT name FROM brands WHERE id = ?", (brand_id,)).fetchone()
    conn.execute("UPDATE brands SET active = 0 WHERE id = ?", (brand_id,))
    conn.commit()
    return _redirect(f"{brand['name']} removed.")


# --- Sub-brands ---

@router.post("/settings/sub-brands/add")
def add_sub_brand(brand_id: int = Form(...), name: str = Form(...), conn=Depends(get_conn)):
    cur = conn.execute("INSERT INTO sub_brands (brand_id, name) VALUES (?, ?)", (brand_id, name))
    conn.commit()
    return _redirect(f"Added sub-brand {name}.")


@router.post("/settings/sub-brands/{sub_brand_id}/rename")
def rename_sub_brand(sub_brand_id: int, name: str = Form(...), conn=Depends(get_conn)):
    old = conn.execute("SELECT name FROM sub_brands WHERE id = ?", (sub_brand_id,)).fetchone()
    conn.execute("UPDATE sub_brands SET name = ? WHERE id = ?", (name, sub_brand_id))
    conn.commit()
    return _redirect(
        "Renamed.", undo_url=f"/settings/sub-brands/{sub_brand_id}/rename", undo_field="name", undo_value=old["name"]
    )


# --- Roles ---

@router.post("/settings/roles/add")
def add_role(name: str = Form(...), conn=Depends(get_conn)):
    cur = conn.execute("INSERT INTO roles (name) VALUES (?)", (name,))
    conn.commit()
    return _redirect(f"Added role {name}.", undo_url=f"/settings/roles/{cur.lastrowid}/delete")


@router.post("/settings/roles/{role_id}/update")
def update_role(
    role_id: int,
    name: str = Form(...),
    can_move: bool = Form(False),
    can_edit: bool = Form(False),
    can_ship: bool = Form(False),
    can_admin: bool = Form(False),
    conn=Depends(get_conn),
):
    role = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    if role["can_admin"] and not can_admin:
        dependents = _role_active_user_count(conn, role_id)
        if dependents and _admin_capable_user_count(conn) - dependents <= 0:
            return _redirect(error="This would leave no one able to manage Settings — assign another admin first.")
    conn.execute(
        "UPDATE roles SET name = ?, can_move = ?, can_edit = ?, can_ship = ?, can_admin = ? WHERE id = ?",
        (name, can_move, can_edit, can_ship, can_admin, role_id),
    )
    conn.commit()
    return _redirect("Role updated.")


@router.post("/settings/roles/{role_id}/delete")
def delete_role(role_id: int, conn=Depends(get_conn)):
    role = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    if role["can_admin"]:
        dependents = _role_active_user_count(conn, role_id)
        if dependents and _admin_capable_user_count(conn) - dependents <= 0:
            return _redirect(error="This would leave no one able to manage Settings — assign another admin first.")
    conn.execute("UPDATE roles SET active = 0 WHERE id = ?", (role_id,))
    conn.commit()
    return _redirect(f"{role['name']} removed.")


# --- Users ---

@router.post("/settings/users/add")
def add_user(name: str = Form(...), conn=Depends(get_conn)):
    cur = conn.execute("INSERT INTO users (name) VALUES (?)", (name,))
    conn.commit()
    return _redirect(f"Added user {name}.", undo_url=f"/settings/users/{cur.lastrowid}/delete")


@router.post("/settings/users/{user_id}/rename")
def rename_user(user_id: int, name: str = Form(...), conn=Depends(get_conn)):
    old = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
    conn.commit()
    return _redirect(
        "Renamed.", undo_url=f"/settings/users/{user_id}/rename", undo_field="name", undo_value=old["name"]
    )


@router.post("/settings/users/{user_id}/delete")
def delete_user(user_id: int, conn=Depends(get_conn)):
    user = conn.execute(
        "SELECT u.name, r.can_admin FROM users u LEFT JOIN roles r ON r.id = u.role_id WHERE u.id = ?",
        (user_id,),
    ).fetchone()
    if user["can_admin"]:
        if _admin_capable_user_count(conn, excluding_user_id=user_id) == 0:
            return _redirect(error="This would leave no one able to manage Settings — assign another admin first.")
    conn.execute("UPDATE users SET active = 0 WHERE id = ?", (user_id,))
    conn.commit()
    return _redirect(f"{user['name']} removed.")


@router.post("/settings/users/{user_id}/role")
def set_user_role(user_id: int, role_id: str = Form(""), conn=Depends(get_conn)):
    user = conn.execute(
        "SELECT u.active, r.can_admin FROM users u LEFT JOIN roles r ON r.id = u.role_id WHERE u.id = ?",
        (user_id,),
    ).fetchone()
    new_role = conn.execute("SELECT can_admin FROM roles WHERE id = ?", (role_id,)).fetchone() if role_id else None
    losing_admin = user["active"] and user["can_admin"] and not (new_role and new_role["can_admin"])
    if losing_admin and _admin_capable_user_count(conn, excluding_user_id=user_id) == 0:
        return _redirect(error="This would leave no one able to manage Settings — assign another admin first.")
    conn.execute("UPDATE users SET role_id = ? WHERE id = ?", (role_id or None, user_id))
    conn.commit()
    return _redirect("Role assigned.")


@router.post("/settings/users/{user_id}/password")
def set_user_password(user_id: int, password: str = Form(...), password_confirm: str = Form(...), conn=Depends(get_conn)):
    if password != password_confirm or len(password) < 4:
        return _redirect(error="Passwords must match and be at least 4 characters.")
    password_hash, salt = auth.hash_password(password)
    conn.execute(
        "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?", (password_hash, salt, user_id)
    )
    conn.commit()
    return _redirect("Password updated.")


# --- Backup / email ---

@router.post("/settings/backup")
def do_backup(conn=Depends(get_conn)):
    backup_to_folder()
    return _redirect("Backed up.")


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
    return _redirect("Saved.")

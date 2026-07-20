import logging
import secrets
import socket
import traceback
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, db, migrations, seed

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

SESSION_COOKIE = "dpr_session"
PUBLIC_PATH_PREFIXES = ("/static/",)
PUBLIC_PATHS = ("/login", "/setup")

logger = logging.getLogger("dpr")


class NotAuthenticated(Exception):
    pass


class PermissionDenied(Exception):
    def __init__(self, bundle: str):
        self.bundle = bundle


PERMISSION_LABELS = {
    "move": "move or undo pieces",
    "edit": "edit or add lots",
    "ship": "ship or reopen a lot",
    "admin": "manage Settings",
}


def lan_url() -> str:
    return f"http://{socket.gethostname()}:8765"


def parse_optional_int(value: str | None) -> int | None:
    """Parse a query/form string into an int, treating '' / None / garbage as
    "no value" instead of raising - query params like a brand filter's "Any"
    option submit an empty string, which FastAPI can't coerce to `int | None`
    on its own."""
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def new_toast_id() -> str:
    return uuid.uuid4().hex[:8]


def get_conn():
    conn = db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


def current_user_id(request: Request) -> int | None:
    return getattr(request.state, "user_id", None)


def base_context(request: Request, conn) -> dict:
    user_id = current_user_id(request)
    current_user = None
    if user_id is not None:
        current_user = conn.execute(
            "SELECT u.id, u.name, r.name AS role_name, "
            "COALESCE(r.can_move, 0) AS can_move, COALESCE(r.can_edit, 0) AS can_edit, "
            "COALESCE(r.can_ship, 0) AS can_ship, COALESCE(r.can_admin, 0) AS can_admin "
            "FROM users u LEFT JOIN roles r ON r.id = u.role_id WHERE u.id = ?",
            (user_id,),
        ).fetchone()
    return {
        "request": request,
        "lan_url": lan_url(),
        "current_user": current_user,
    }


def require_permission(bundle: str):
    """Dependency factory: the logged-in user's role must have this bundle's
    can_* flag set, else raise PermissionDenied (handled into a graceful 403)."""

    def _check(request: Request, conn=Depends(get_conn)):
        user_id = current_user_id(request)
        if user_id is None:
            raise NotAuthenticated()
        row = conn.execute(
            f"SELECT COALESCE(r.can_{bundle}, 0) AS allowed FROM users u "
            f"LEFT JOIN roles r ON r.id = u.role_id WHERE u.id = ? AND u.active = 1",
            (user_id,),
        ).fetchone()
        if row is None or not row["allowed"]:
            raise PermissionDenied(bundle)

    return _check


def _setup_needed(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE r.can_admin = 1 AND u.active = 1 AND u.password_hash IS NOT NULL LIMIT 1"
    ).fetchone()
    return row is None


def _setup_target_user(conn):
    return conn.execute(
        "SELECT u.id, u.name FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE r.can_admin = 1 AND u.active = 1 AND u.password_hash IS NULL "
        "ORDER BY u.id LIMIT 1"
    ).fetchone()


def create_app() -> FastAPI:
    app = FastAPI(title="DPR")
    app.state.secret_key = secrets.token_bytes(32)
    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    @app.exception_handler(NotAuthenticated)
    async def handle_not_authenticated(request: Request, exc: NotAuthenticated):
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=303)

    @app.exception_handler(PermissionDenied)
    async def handle_permission_denied(request: Request, exc: PermissionDenied):
        action = PERMISSION_LABELS.get(exc.bundle, "do that")
        message = f"You don't have permission to {action}. Ask the owner to update your role in Settings."
        if request.headers.get("hx-request"):
            return HTMLResponse(f'<div class="error-banner">{message}</div>', status_code=403)
        return templates.TemplateResponse(
            request, "error.html", {"request": request, "message": message}, status_code=403
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        logger.error("Unhandled error on %s %s:\n%s", request.method, request.url.path, traceback.format_exc())
        message = "Something went wrong on this action. Nothing was saved. Try again, and if it keeps happening, check the terminal window DPR is running in."
        if request.headers.get("hx-request"):
            return HTMLResponse(f'<div class="error-banner">{message}</div>', status_code=500)
        return templates.TemplateResponse(request, "error.html", {"request": request, "message": message}, status_code=500)

    @app.on_event("startup")
    def on_startup():
        conn = db.get_connection()
        try:
            db.init_db(conn)
            seed.seed_if_empty(conn)
            migrations.run_migrations(conn)
            from app.invariants import check_invariants

            check_invariants(conn)
        finally:
            conn.close()

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith(PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        if not getattr(app.state, "setup_complete", False):
            conn = db.get_connection()
            try:
                needed = _setup_needed(conn)
            finally:
                conn.close()
            if needed:
                if path != "/setup":
                    return RedirectResponse(url="/setup", status_code=303)
                return await call_next(request)
            app.state.setup_complete = True

        if path in PUBLIC_PATHS:
            return await call_next(request)

        user_id = auth.verify_session(request.cookies.get(SESSION_COOKIE), app.state.secret_key)
        if user_id is None:
            return RedirectResponse(url=f"/login?next={path}", status_code=303)
        request.state.user_id = user_id
        return await call_next(request)

    @app.get("/setup", response_class=HTMLResponse)
    def setup_form(request: Request, conn=Depends(get_conn)):
        target = _setup_target_user(conn)
        return templates.TemplateResponse(
            request, "setup.html", {"request": request, "target_name": target["name"] if target else None}
        )

    @app.post("/setup")
    def setup_submit(
        request: Request,
        password: str = Form(...),
        password_confirm: str = Form(...),
        conn=Depends(get_conn),
    ):
        target = _setup_target_user(conn)
        if target is None:
            return RedirectResponse(url="/", status_code=303)
        if password != password_confirm or len(password) < 4:
            return templates.TemplateResponse(
                request,
                "setup.html",
                {
                    "request": request,
                    "target_name": target["name"],
                    "error": "Passwords must match and be at least 4 characters.",
                },
            )
        password_hash, salt = auth.hash_password(password)
        conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
            (password_hash, salt, target["id"]),
        )
        conn.commit()
        app.state.setup_complete = True
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(SESSION_COOKIE, auth.sign_session(target["id"], app.state.secret_key))
        return response

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/", error: str = "", conn=Depends(get_conn)):
        users = conn.execute("SELECT id, name FROM users WHERE active = 1 ORDER BY name").fetchall()
        return templates.TemplateResponse(
            request, "login.html", {"request": request, "users": users, "next": next, "error": error}
        )

    @app.post("/login")
    def login_submit(
        request: Request,
        user_id: int = Form(...),
        password: str = Form(...),
        next: str = Form("/"),
        conn=Depends(get_conn),
    ):
        user = conn.execute(
            "SELECT id, password_hash, password_salt FROM users WHERE id = ? AND active = 1", (user_id,)
        ).fetchone()
        if user is None or not auth.verify_password(password, user["password_hash"], user["password_salt"]):
            from urllib.parse import quote

            return RedirectResponse(
                url=f"/login?error={quote('Incorrect username or password.')}&next={quote(next)}",
                status_code=303,
            )
        response = RedirectResponse(url=next or "/", status_code=303)
        response.set_cookie(SESSION_COOKIE, auth.sign_session(user["id"], app.state.secret_key))
        return response

    @app.post("/logout")
    def logout():
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.post("/quit")
    def quit_app(_perm=Depends(require_permission("admin"))):
        import os
        import threading

        def shutdown():
            os._exit(0)

        threading.Timer(0.3, shutdown).start()
        return RedirectResponse(url="/", status_code=303)

    from app.routes import (
        analytics as analytics_routes,
        archive as archive_routes,
        exporter_routes,
        importer_routes,
        lots as lots_routes,
        main_screen,
        settings as settings_routes,
    )

    app.include_router(main_screen.router)
    app.include_router(lots_routes.router)
    app.include_router(archive_routes.router)
    app.include_router(importer_routes.router)
    app.include_router(exporter_routes.router)
    app.include_router(analytics_routes.router)
    app.include_router(settings_routes.router)

    return app

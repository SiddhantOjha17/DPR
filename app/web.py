import socket
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db, seed
from app.config import db_path

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

CURRENT_USER_COOKIE = "dpr_user_id"


def lan_url() -> str:
    return f"http://{socket.gethostname()}:8765"


def get_conn():
    conn = db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


def current_user_id(request: Request) -> int | None:
    raw = request.cookies.get(CURRENT_USER_COOKIE)
    return int(raw) if raw else None


def base_context(request: Request, conn) -> dict:
    users = conn.execute("SELECT id, name FROM users WHERE active = 1 ORDER BY name").fetchall()
    return {
        "request": request,
        "lan_url": lan_url(),
        "users": users,
        "current_user_id": current_user_id(request),
    }


def create_app() -> FastAPI:
    app = FastAPI(title="DPR")
    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    @app.on_event("startup")
    def on_startup():
        conn = db.get_connection()
        try:
            db.init_db(conn)
            seed.seed_if_empty(conn)
            from app.invariants import check_invariants

            check_invariants(conn)
        finally:
            conn.close()

    @app.post("/session/user")
    def set_user(request: Request, user_id: int = Form(...)):
        response = RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)
        response.set_cookie(CURRENT_USER_COOKIE, str(user_id))
        return response

    @app.post("/quit")
    def quit_app():
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

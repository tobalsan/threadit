from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from threaddit import routes_board, routes_feed, routes_users
from threaddit.core import ApiError
from threaddit.db import Database

SKILL_PATH = Path(__file__).resolve().parent / "skill.md"
DEFAULT_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;"
        " object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


def create_app(database_path, static_dir: Path | str | None = None) -> FastAPI:
    app = FastAPI(title="Threaddit", version="0.1.0")
    app.state.db = Database(database_path)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_: Request, exc: RequestValidationError):
        parts = [
            f"{'.'.join(str(p) for p in e['loc'][1:]) or e['loc'][0]}: {e['msg']}"
            for e in exc.errors()
        ]
        return _error(422, "invalid_input", "; ".join(parts))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        codes = {404: "not_found", 405: "method_not_allowed"}
        return _error(exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.get("/SKILL.md", include_in_schema=False)
    @app.get("/skill.md", include_in_schema=False)
    def skill():
        return Response(
            SKILL_PATH.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8"
        )

    app.include_router(routes_users.router)
    app.include_router(routes_board.router)
    app.include_router(routes_feed.router)

    static = Path(static_dir) if static_dir is not None else DEFAULT_STATIC_DIR
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app

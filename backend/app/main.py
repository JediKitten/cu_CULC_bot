from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    admin,
    analytics,
    applications,
    auth,
    board,
    books,
    events,
    me,
    profile,
    social,
)
from app.config import get_config
from app.services import tg
from app.services.books import merge


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Оба клиента ленивые: если их не трогали, закрывать нечего.
    await merge.aclose()
    await tg.aclose()


app = FastAPI(title="Литклуб", version="0.1.0", lifespan=lifespan)

# Mini App грузится с домена фронта, а не с домена API.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(books.router)
app.include_router(board.router)
app.include_router(applications.router)
app.include_router(events.router)
app.include_router(me.router)
app.include_router(social.router)
app.include_router(admin.router)
app.include_router(analytics.router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


# --- Статика Mini App ------------------------------------------------------
#
# В проде перед приложением нет nginx: собранный фронтенд отдаёт сам FastAPI.
# Тот же origin, что и API, — значит фронтенду не нужны ни VITE_API_URL, ни CORS.
# Монтируется последним, чтобы маршруты /api и /health имели приоритет.

_frontend = Path(get_config().frontend_dir)

if (_frontend / "index.html").is_file():
    if (_frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_frontend / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """SPA-фолбэк: неизвестный путь отдаёт index.html, маршрутизация на клиенте."""
        # Неизвестный /api/... должен быть честной 404, а не страницей приложения:
        # иначе опечатка в адресе выглядит как пустой экран вместо ошибки.
        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Неизвестный метод API")

        candidate = (_frontend / path).resolve()
        # Проверка на выход за пределы каталога: путь приходит из запроса.
        if path and _frontend.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_frontend / "index.html")

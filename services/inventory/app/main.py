"""FastAPI application entry point."""

from fastapi import FastAPI, HTTPException, status

from app import __version__
from app.config import get_settings
from app.db import check_database_connection
from app.errors import install_error_handlers
from app.routers.inventory import router as inventory_router
from app.routers.vendors import router as vendors_router


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Inventory system of record for the SimplifyNext prototype.",
)
install_error_handlers(app)
app.include_router(inventory_router)
app.include_router(vendors_router)


@app.get(
    "/health",
    tags=["system"],
    summary="Check API and database health",
)
def health() -> dict[str, str]:
    """Report healthy only when the API can reach Postgres."""

    try:
        check_database_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return {"status": "ok", "database": "ok"}

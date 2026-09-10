"""FastAPI application entry point."""

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pantry_common.security import require_operator

from app import __version__
from app.config import get_settings
from app.db import check_database_connection
from app.errors import install_error_handlers
from app.routers.inventory import router as inventory_router
from app.routers.orders import router as orders_router
from app.routers.settings import router as settings_router
from app.routers.vendors import router as vendors_router


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Inventory system of record for the SimplifyNext prototype.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, change this to your frontend URL
    allow_methods=["*"],
    allow_headers=["*"],
)

install_error_handlers(app)
# Stock, orders, and vendor routes carry no auth of their own -- they are
# reachable by both charity staff (a JWT via the frontend) and the
# orchestrator's agent (the internal service token). require_operator accepts
# either. settings_router is deliberately left unwrapped: GET /settings is
# intentionally public (see its own docstring) and PATCH already guards
# itself with require_charity, since only a human should raise the budget.
operator_only = [Depends(require_operator)]
app.include_router(inventory_router, dependencies=operator_only)
app.include_router(orders_router, dependencies=operator_only)
app.include_router(vendors_router, dependencies=operator_only)
app.include_router(settings_router)


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

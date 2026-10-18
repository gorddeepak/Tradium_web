"""Health check, same path and body as the Express app."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health():
    # Does no database or provider work, like the Express version.
    return {"ok": True}

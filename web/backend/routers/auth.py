"""Auth router — user info endpoint (identity from Azure EasyAuth headers)."""

from fastapi import APIRouter, Depends

from auth import get_current_user
from models import WebUser

router = APIRouter()


@router.get("/me")
async def get_me(user: WebUser = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
    }

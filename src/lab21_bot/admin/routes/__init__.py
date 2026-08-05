from __future__ import annotations

from fastapi import APIRouter

from lab21_bot.admin.routes import auth, dashboard, moderation, people, shop

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(people.router)
api_router.include_router(shop.router)
api_router.include_router(moderation.router)

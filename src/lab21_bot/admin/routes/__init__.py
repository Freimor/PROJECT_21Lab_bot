from __future__ import annotations

from fastapi import APIRouter

from lab21_bot.admin.routes import (
    auth,
    dashboard,
    faq,
    feedback,
    gamification,
    llm_posts,
    people,
    publications,
    settings,
    shop,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(people.router)
api_router.include_router(shop.router)
api_router.include_router(publications.router)
api_router.include_router(llm_posts.router)
api_router.include_router(settings.router)
api_router.include_router(feedback.router)
api_router.include_router(gamification.router)
api_router.include_router(faq.router)

from __future__ import annotations

from fastapi import APIRouter

from lab21_bot.miniapp.routes import faq, join, jobs, me, quests, shop, skills, staff, submissions

router = APIRouter()
router.include_router(me.router)
router.include_router(faq.router)
router.include_router(join.router)
router.include_router(shop.router)
router.include_router(jobs.router)
router.include_router(submissions.router)
router.include_router(quests.router)
router.include_router(skills.router)
router.include_router(staff.router)

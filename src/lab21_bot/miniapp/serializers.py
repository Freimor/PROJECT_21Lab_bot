from __future__ import annotations

from lab21_bot.data import skill_title
from lab21_bot.models import (
    ContentItem,
    JoinApplication,
    JoinStatus,
    Order,
    Product,
    ServiceJob,
    User,
)
from lab21_bot.services.access import Permission, has_permission


def user_to_dict(user: User) -> dict:
    staff_role = user.staff_role.value if hasattr(user.staff_role, "value") else user.staff_role
    rank = user.rank.value if hasattr(user.rank, "value") else user.rank
    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "full_name": user.full_name,
        "bio": user.bio,
        "staff_role": staff_role,
        "rank": rank,
        "balance": user.balance,
        "respect": user.respect,
        "skill_ids": list(user.skill_ids or []),
        "skills": [
            {"id": skill_id, "title": skill_title(skill_id)}
            for skill_id in (user.skill_ids or [])
        ],
        "job_notify_enabled": user.job_notify_enabled,
        "ritual_streak": user.ritual_streak,
        "is_approved": user.is_approved,
        "is_active": user.is_active,
        "registered": True,
        "permissions": [perm.value for perm in Permission if has_permission(user, perm)],
        "is_staff": user.staff_role is not None,
    }


def join_application_to_dict(app: JoinApplication) -> dict:
    status = app.status.value if hasattr(app.status, "value") else app.status
    kind = app.kind.value if hasattr(app.kind, "value") else app.kind
    return {
        "id": app.id,
        "kind": kind,
        "status": status,
        "bio": app.bio,
        "skills_text": app.skills_text,
        "skill_ids": list(app.skill_ids or []),
        "decision_note": app.decision_note,
        "created_at": app.created_at.isoformat() if app.created_at else None,
        "expires_at": app.expires_at.isoformat() if app.expires_at else None,
    }


def product_to_dict(product: Product) -> dict:
    kind = product.kind.value if hasattr(product.kind, "value") else product.kind
    rank = product.min_rank.value if hasattr(product.min_rank, "value") else product.min_rank
    available = product.is_visible and (product.stock is None or int(product.stock) > 0)
    return {
        "id": product.id,
        "article": product.article,
        "name": product.name,
        "description": product.description,
        "kind": kind,
        "price": product.price,
        "min_rank": rank,
        "stock": product.stock,
        "max_per_user": product.max_per_user,
        "skill_ids": list(product.skill_ids or []),
        "image_url": f"/uploads/products/{product.image_path}" if product.image_path else None,
        "available": available,
    }


def order_to_dict(order: Order) -> dict:
    status = order.status.value if hasattr(order.status, "value") else order.status
    return {
        "id": order.id,
        "product_id": order.product_id,
        "product_name": order.product.name if order.product else None,
        "qty": order.quantity,
        "total_price": order.total_price,
        "status": status,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def job_to_dict(job: ServiceJob) -> dict:
    status = job.status.value if hasattr(job.status, "value") else job.status
    return {
        "id": job.id,
        "order_id": job.order_id,
        "status": status,
        "description": job.description,
        "skill_ids": list(job.skill_ids or []),
        "price": job.price,
        "respect": job.respect_reward,
        "assignee_note": job.assignee_note,
        "result_text": job.result_text,
        "customer_id": job.customer_id,
        "assignee_id": job.assignee_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def content_to_dict(item: ContentItem) -> dict:
    kind = item.kind.value if hasattr(item.kind, "value") else item.kind
    status = item.status.value if hasattr(item.status, "value") else item.status
    return {
        "id": item.id,
        "kind": kind,
        "status": status,
        "source_text": item.source_text,
        "draft_text": item.draft_text,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def join_status_summary(app: JoinApplication | None, user: User) -> dict:
    if user.is_approved:
        return {"state": "approved"}
    if app is None:
        return {"state": "none"}
    status = app.status.value if hasattr(app.status, "value") else app.status
    if status in {JoinStatus.PENDING.value, JoinStatus.SKILL_VALIDATION.value}:
        return {"state": "pending", "application": join_application_to_dict(app)}
    if status == JoinStatus.REJECTED.value:
        return {"state": "rejected", "application": join_application_to_dict(app)}
    if status == JoinStatus.EXPIRED.value:
        return {"state": "expired", "application": join_application_to_dict(app)}
    return {"state": "unknown", "application": join_application_to_dict(app)}

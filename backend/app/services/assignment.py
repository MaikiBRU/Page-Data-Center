from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.user import User

ASSIGNMENT_MODES = {"manual", "owner", "round_robin"}


def _active_user_emails(db: Session) -> list[str]:
    rows = (
        db.query(User)
        .filter(User.is_active == True)  # noqa: E712
        .order_by(User.created_at.asc(), User.id.asc())
        .all()
    )
    return [row.email for row in rows if row.email]


def pick_assignee(
    db: Session,
    dataset: Dataset,
    active_users: list[str] | None = None,
) -> str | None:
    mode = dataset.assignment_mode or "manual"
    if mode not in ASSIGNMENT_MODES:
        mode = "manual"

    if mode == "owner":
        owner = (dataset.assignment_owner or "").strip()
        if not owner:
            return None
        owner_row = (
            db.query(User)
            .filter(User.email == owner, User.is_active == True)  # noqa: E712
            .first()
        )
        return owner_row.email if owner_row else None

    if mode == "round_robin":
        users = active_users if active_users is not None else _active_user_emails(db)
        if not users:
            return None
        cursor = dataset.assignment_cursor or 0
        index = cursor % len(users)
        dataset.assignment_cursor = (index + 1) % len(users)
        return users[index]

    return None

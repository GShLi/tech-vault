"""Built-in super administrator bootstrap."""

from __future__ import annotations

from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.core.passwords import hash_password
from backend.app.db.models import User


def seed_builtin_admin(session_factory, settings: Settings) -> None:
    """Create the protected administrator once and repair its flags."""
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == settings.admin_email))
        if user is None:
            session.add(
                User(
                    email=settings.admin_email,
                    display_name=settings.admin_display_name,
                    password_hash=hash_password(settings.admin_password),
                    is_super_admin=True,
                    is_builtin=True,
                )
            )
            session.commit()
            return

        changed = False
        if not user.is_super_admin:
            user.is_super_admin = True
            changed = True
        if not user.is_builtin:
            user.is_builtin = True
            changed = True
        if changed:
            session.commit()

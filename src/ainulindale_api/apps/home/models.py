from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ainulindale_api.core import db


class HomeUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    google_sub: str
    email: str
    name: str = ""
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    last_login_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )


class HomeSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    user_id: str | None = None
    email: str | None = None
    name: str | None = None
    is_authenticated: bool = False
    state: str | None = None
    nonce: str | None = None
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    expires_at: datetime.datetime | None = None


async def create_user(google_sub: str, email: str, name: str = "") -> HomeUser:
    now = datetime.datetime.now(datetime.UTC)
    user = HomeUser(
        google_sub=google_sub,
        email=email.strip().lower(),
        name=name,
        created_at=now,
        last_login_at=now,
    )
    if db.db is not None:
        await db.db.home_users.insert_one(user.model_dump(by_alias=True))
    return user


async def get_user_by_sub(google_sub: str) -> HomeUser | None:
    if db.db is None:
        return None
    data = await db.db.home_users.find_one({"google_sub": google_sub})
    if data:
        return HomeUser(**data)
    return None


async def get_user_by_email(email: str) -> HomeUser | None:
    if db.db is None:
        return None
    data = await db.db.home_users.find_one({"email": email.strip().lower()})
    if data:
        return HomeUser(**data)
    return None


async def get_user(user_id: str) -> HomeUser | None:
    if db.db is None:
        return None
    data = await db.db.home_users.find_one({"_id": user_id})
    if data:
        return HomeUser(**data)
    return None


async def update_user_login(user_id: str) -> None:
    if db.db is None:
        return
    now = datetime.datetime.now(datetime.UTC)
    await db.db.home_users.update_one(
        {"_id": user_id},
        {"$set": {"last_login_at": now}},
    )


async def create_session(
    user_id: str | None = None,
    email: str | None = None,
    name: str | None = None,
    is_authenticated: bool = False,
    state: str | None = None,
    nonce: str | None = None,
    duration_days: int = 30,
) -> HomeSession:
    now = datetime.datetime.now(datetime.UTC)
    expires_at = now + datetime.timedelta(days=duration_days)
    session = HomeSession(
        user_id=user_id,
        email=email.strip().lower() if email else None,
        name=name,
        is_authenticated=is_authenticated,
        state=state,
        nonce=nonce,
        created_at=now,
        expires_at=expires_at,
    )
    if db.db is not None:
        await db.db.home_sessions.insert_one(session.model_dump(by_alias=True))
    return session


async def get_session(session_id: str) -> HomeSession | None:
    if db.db is None:
        return None
    data = await db.db.home_sessions.find_one({"_id": session_id})
    if not data:
        return None
    session = HomeSession(**data)
    # Check expiry if present
    if session.expires_at:
        now = datetime.datetime.now(datetime.UTC)
        # Ensure UTC timezone comparability
        exp = session.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=datetime.UTC)
        if now > exp:
            await delete_session(session_id)
            return None
    return session


async def update_session(session_id: str, **kwargs: Any) -> None:
    if db.db is None:
        return
    await db.db.home_sessions.update_one({"_id": session_id}, {"$set": kwargs})


async def delete_session(session_id: str) -> None:
    if db.db is None:
        return
    await db.db.home_sessions.delete_one({"_id": session_id})

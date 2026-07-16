import datetime
import uuid

from pydantic import BaseModel, Field

from ainulindale_api.core import db


class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    google_sub: str
    email: str
    name: str
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )

class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    principal_id: str
    is_authenticated: bool = False
    state: str | None = None
    nonce: str | None = None
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )

class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    owner_id: str
    filename: str
    status: str = "queued"  # queued, processing, succeeded, failed
    transcript: str | None = None
    error: str | None = None
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    updated_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )

async def create_user(google_sub: str, email: str, name: str) -> User:
    user = User(google_sub=google_sub, email=email, name=name)
    await db.db.eridian_echo_users.insert_one(user.model_dump(by_alias=True))
    return user

async def get_user_by_sub(google_sub: str) -> User | None:
    data = await db.db.eridian_echo_users.find_one({"google_sub": google_sub})
    if data:
        return User(**data)
    return None

async def get_user(user_id: str) -> User | None:
    data = await db.db.eridian_echo_users.find_one({"_id": user_id})
    if data:
        return User(**data)
    return None

async def create_session(principal_id: str, is_authenticated: bool = False) -> Session:
    session = Session(principal_id=principal_id, is_authenticated=is_authenticated)
    await db.db.eridian_echo_sessions.insert_one(session.model_dump(by_alias=True))
    return session

async def get_session(session_id: str) -> Session | None:
    data = await db.db.eridian_echo_sessions.find_one({"_id": session_id})
    if data:
        return Session(**data)
    return None

async def update_session(session_id: str, **kwargs):
    await db.db.eridian_echo_sessions.update_one({"_id": session_id}, {"$set": kwargs})

async def delete_session(session_id: str):
    await db.db.eridian_echo_sessions.delete_one({"_id": session_id})

async def link_jobs_to_user(guest_principal_id: str, user_id: str):
    await db.db.eridian_echo_jobs.update_many(
        {"owner_id": guest_principal_id},
        {
            "$set": {
                "owner_id": user_id,
                "updated_at": datetime.datetime.now(datetime.UTC),
            }
        },
    )

async def create_job(owner_id: str, filename: str) -> Job:
    job = Job(owner_id=owner_id, filename=filename)
    await db.db.eridian_echo_jobs.insert_one(job.model_dump(by_alias=True))
    return job


async def get_job(job_id: str) -> Job | None:
    data = await db.db.eridian_echo_jobs.find_one({"_id": job_id})
    if data:
        return Job(**data)
    return None


async def get_jobs_for_owner(owner_id: str) -> list[Job]:
    cursor = db.db.eridian_echo_jobs.find({"owner_id": owner_id}).sort("created_at", -1)
    jobs = []
    async for data in cursor:
        jobs.append(Job(**data))
    return jobs


async def update_job_status(
    job_id: str, status: str, transcript: str | None = None, error: str | None = None
):
    update_data = {"status": status, "updated_at": datetime.datetime.now(datetime.UTC)}
    if transcript is not None:
        update_data["transcript"] = transcript
    if error is not None:
        update_data["error"] = error

    await db.db.eridian_echo_jobs.update_one({"_id": job_id}, {"$set": update_data})


async def delete_job(job_id: str):
    await db.db.eridian_echo_jobs.delete_one({"_id": job_id})

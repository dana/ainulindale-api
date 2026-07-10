import datetime
import uuid
from typing import Optional, List
from pydantic import BaseModel, Field
from ainulindale_api.core import db

class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    owner_id: str
    filename: str
    status: str = "queued" # queued, processing, succeeded, failed
    transcript: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

async def create_job(owner_id: str, filename: str) -> Job:
    job = Job(owner_id=owner_id, filename=filename)
    await db.db.eridian_echo_jobs.insert_one(job.model_dump(by_alias=True))
    return job

async def get_job(job_id: str) -> Optional[Job]:
    data = await db.db.eridian_echo_jobs.find_one({"_id": job_id})
    if data:
        return Job(**data)
    return None

async def get_jobs_for_owner(owner_id: str) -> List[Job]:
    cursor = db.db.eridian_echo_jobs.find({"owner_id": owner_id}).sort("created_at", -1)
    jobs = []
    async for data in cursor:
        jobs.append(Job(**data))
    return jobs

async def update_job_status(job_id: str, status: str, transcript: Optional[str] = None, error: Optional[str] = None):
    update_data = {
        "status": status,
        "updated_at": datetime.datetime.utcnow()
    }
    if transcript is not None:
        update_data["transcript"] = transcript
    if error is not None:
        update_data["error"] = error
        
    await db.db.eridian_echo_jobs.update_one(
        {"_id": job_id},
        {"$set": update_data}
    )

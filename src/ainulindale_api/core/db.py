import os
from motor.motor_asyncio import AsyncIOMotorClient

# Default to the cluster DNS if not specified
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb.mongodb.svc.cluster.local:27017")
DATABASE_NAME = "ainulindale"

client: AsyncIOMotorClient = None
db = None

def get_db():
    return db

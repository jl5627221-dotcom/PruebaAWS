from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timezone
from enum import Enum


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection - use environment variable
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'taskflow_db')

client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# Create the main app
app = FastAPI(
    title="TaskFlow API",
    description="Task Management API for AWS App Runner",
    version="1.0.0"
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Enums
class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# Define Models
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        extra = "ignore"

class StatusCheckCreate(BaseModel):
    client_name: str


# Task Models
class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: Optional[str] = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        extra = "ignore"

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    priority: TaskPriority = TaskPriority.MEDIUM

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None

class TaskStats(BaseModel):
    total: int
    pending: int
    in_progress: int
    completed: int
    high_priority: int
    medium_priority: int
    low_priority: int


# Health check endpoint (required for App Runner)
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "TaskFlow API"}

@api_router.get("/")
async def root():
    return {"message": "Welcome to TaskFlow API"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.dict()
    status_obj = StatusCheck(**status_dict)
    
    doc = status_obj.dict()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks


# Task Routes
@api_router.get("/tasks", response_model=List[Task])
async def get_tasks(status: Optional[TaskStatus] = None, priority: Optional[TaskPriority] = None):
    query = {}
    if status:
        query["status"] = status.value
    if priority:
        query["priority"] = priority.value
    
    tasks = await db.tasks.find(query, {"_id": 0}).to_list(1000)
    
    for task in tasks:
        if isinstance(task.get('created_at'), str):
            task['created_at'] = datetime.fromisoformat(task['created_at'])
        if isinstance(task.get('updated_at'), str):
            task['updated_at'] = datetime.fromisoformat(task['updated_at'])
    
    return tasks

@api_router.post("/tasks", response_model=Task)
async def create_task(task_input: TaskCreate):
    task_dict = task_input.dict()
    task_obj = Task(**task_dict)
    
    doc = task_obj.dict()
    doc['created_at'] = doc['created_at'].isoformat()
    doc['updated_at'] = doc['updated_at'].isoformat()
    
    await db.tasks.insert_one(doc)
    return task_obj

@api_router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str):
    task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if isinstance(task.get('created_at'), str):
        task['created_at'] = datetime.fromisoformat(task['created_at'])
    if isinstance(task.get('updated_at'), str):
        task['updated_at'] = datetime.fromisoformat(task['updated_at'])
    
    return task

@api_router.put("/tasks/{task_id}", response_model=Task)
async def update_task(task_id: str, task_update: TaskUpdate):
    existing_task = await db.tasks.find_one({"id": task_id})
    if not existing_task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    update_data = {k: v for k, v in task_update.dict().items() if v is not None}
    if update_data:
        update_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        await db.tasks.update_one({"id": task_id}, {"$set": update_data})
    
    updated_task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    
    if isinstance(updated_task.get('created_at'), str):
        updated_task['created_at'] = datetime.fromisoformat(updated_task['created_at'])
    if isinstance(updated_task.get('updated_at'), str):
        updated_task['updated_at'] = datetime.fromisoformat(updated_task['updated_at'])
    
    return updated_task

@api_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    result = await db.tasks.delete_one({"id": task_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"message": "Task deleted successfully"}

@api_router.get("/tasks-stats", response_model=TaskStats)
async def get_task_stats():
    total = await db.tasks.count_documents({})
    pending = await db.tasks.count_documents({"status": "pending"})
    in_progress = await db.tasks.count_documents({"status": "in_progress"})
    completed = await db.tasks.count_documents({"status": "completed"})
    high_priority = await db.tasks.count_documents({"priority": "high"})
    medium_priority = await db.tasks.count_documents({"priority": "medium"})
    low_priority = await db.tasks.count_documents({"priority": "low"})
    
    return TaskStats(
        total=total,
        pending=pending,
        in_progress=in_progress,
        completed=completed,
        high_priority=high_priority,
        medium_priority=medium_priority,
        low_priority=low_priority
    )


# Include the router in the main app
app.include_router(api_router)

# CORS - Allow all origins for now (configure properly in production)
allowed_origins = os.environ.get('CORS_ORIGINS', '*').split(',')

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=allowed_origins if allowed_origins != ['*'] else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    logger.info("TaskFlow API starting up...")
    logger.info(f"Connected to MongoDB: {db_name}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    logger.info("TaskFlow API shutting down...")

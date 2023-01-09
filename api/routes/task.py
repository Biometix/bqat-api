import json
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from api.config.models import EditTaskLog, Status, TaskLog, TaskQueue

router = APIRouter()


@router.post("/", response_description="New task appended and logged")
async def append_task(request: Request, log: TaskLog) -> dict:
    await log.create()
    queue_item = TaskQueue(total=len(log.input)).dict()
    rds = request.app.queue
    await rds.lpush("task_queue", log.tid)
    await rds.set(log.tid, json.dumps(queue_item))
    return {"message": "Successful, new task added."}


@router.get("/", response_description="Task logs retrieved")
async def get_task_logs() -> List[TaskLog]:
    logs = await TaskLog.find_all().to_list()
    return logs


@router.get("/{task_id}", response_description="Task log retrieved")
async def get_task_log(task_id: UUID) -> TaskLog:
    log = await TaskLog.find_one(TaskLog.tid == str(task_id))
    return log


@router.put("/{task_id}", response_description="Task log retrieved")
async def update_task_log(task_id: UUID, edit: EditTaskLog) -> TaskLog:
    edit = {k: v for k, v in edit.dict().items() if v is not None}
    edit_query = {"$set": {field: value for field, value in edit.items()}}
    log = await TaskLog.find_one(TaskLog.tid == str(task_id))
    if not log:
        raise HTTPException(status_code=404, detail="Task log not found!")
    await log.update(edit_query)
    return log


@router.delete("/{task_id}", response_description="Task log removed")
async def delete_task_log(request: Request, task_id: UUID) -> dict:
    log = await TaskLog.find_one(TaskLog.tid == str(task_id))
    if not log:
        raise HTTPException(status_code=404, detail="Task log not found!")
    await log.delete()
    queue = request.app.queue
    await queue.lrem("task_queue", 1, str(task_id))
    await queue.delete(str(task_id))
    return {"message": "Successful, task log removed."}


@router.post("/{task_id}/top", response_description="Task moved to top")
async def top_task(request: Request, task_id: UUID) -> dict:
    queue = request.app.queue
    await queue.lrem("task_queue", 1, str(task_id))
    await queue.rpush("task_queue", str(task_id))
    return {"message": f"Successful, task [{task_id}] moved to front of the queue."}


@router.post("/reload", response_description="Task queue reloaded")
async def reload_task(request: Request) -> dict:
    logs = await TaskLog.find(TaskLog.status != Status.done).to_list(length=None)
    queue = request.app.queue
    for log in logs:
        await queue.lpush("task_queue", log.tid)
        if not await queue.exists(log.tid):
            await queue.set(
                tid,
                json.dumps(
                    TaskQueue(
                        total=len(log.input),
                        done=len(log.finished),
                        eta=0
                    ).dict()
                )
            )
    return {"message": "Successful, task queue reloaded from logs."}


@router.get("/queue", response_description="Task queue retrieved")
async def get_queue(request: Request) -> list:
    queue = request.app.queue
    queue = await queue.lrange("task_queue", 0, -1)
    return queue


@router.delete("/queue", response_description="Task queue cleared")
async def clear_queue(request: Request):
    queue = request.app.queue
    tasks = await queue.lrange("task_queue", 0, -1)
    for item in tasks:
        await queue.delete(item)
    await queue.delete("queue")
    return {"message": "Successful, task queue cleared."}


@router.post("/queue/push", response_description="Task queue item appended")
async def push_queue_item(request: Request, tid: UUID) -> dict:
    queue = request.app.queue
    await queue.lpush("task_queue", str(tid))
    return {"message": "Successful, task queue item appended."}


@router.post("/queue/pop", response_description="Task queue item released")
async def pop_queue_item(request: Request) -> dict:
    queue = request.app.queue
    item = await queue.rpop("queue")
    return item

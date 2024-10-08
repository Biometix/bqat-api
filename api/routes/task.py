import json
import pickle
from pathlib import Path
from typing import Union
from uuid import UUID

import ray
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from api.config import Settings
from api.config.models import (
    # EditTaskLog,
    OutlierDetectionLog,
    PreprocessingLog,
    ReportLog,
    Status,
    TaskLog,
)
from api.utils import (
    run_outlier_detection_tasks,
    run_preprocessing_tasks,
    run_report_tasks,
)

router = APIRouter()


# @router.post("/", response_description="New task appended and logged")
# async def append_task(request: Request, log: TaskLog) -> dict:
#     await log.create()
#     queue_item = TaskQueue(total=len(log.input)).dict()
#     rds = request.app.queue
#     await rds.lpush("task_queue", log.tid)
#     await rds.set(log.tid, json.dumps(queue_item))
#     return {"message": "Successful, new task added."}


@router.get(
    "/logs/scan",
    response_description="All scan task logs retrieved",
    description="Retrieves detailed information about all active and completed tasks including their statuses, options, collections, inputs, and processing details."
)
async def get_all_task_logs(request: Request) -> list:
    logs = (
        await request.app.log["tasks"]
        .aggregate(
            [
                {
                    "$project": {
                        "_id": 0,
                        "options": 1,
                        "collection": 1,
                        "status": 1,
                        "tid": 1,
                        "input": 1,
                        "total": 1,
                        "finished": 1,
                        "elapse": 1,
                        "modified": 1,
                    },
                },
            ]
        )
        .to_list(length=None)
    )
    return logs


@router.get(
    "/logs/report",
    response_description="All report task logs retrieved",
    description="Retrieves detailed information about all generated report logs, including their statuses, options, associated collections, external inputs, and file details."

)
async def get_all_report_logs(request: Request) -> list:
    logs = (
        await request.app.log["reports"]
        .aggregate(
            [
                {
                    "$project": {
                        "_id": 0,
                        "options": 1,
                        "metadata": 1,
                        "collection": 1,
                        "status": 1,
                        "tid": 1,
                        "external_input": 1,
                        "file_id": 1,
                        "filename": 1,
                        "modified": 1,
                    },
                },
            ]
        )
        .to_list(length=None)
    )
    return logs


@router.get(
    "/logs/outlier",
    response_description="All outlier detection task logs retrieved",
    description="Retrieves detailed information about all outlier detection logs, including their statuses, options, associated collections, and modification timestamps."

)
async def get_all_outlier_logs(request: Request) -> list:
    logs = (
        await request.app.log["outliers"]
        .aggregate(
            [
                {
                    "$project": {
                        "_id": 0,
                        "options": 1,
                        "collection": 1,
                        "status": 1,
                        "tid": 1,
                        "modified": 1,
                    },
                },
            ]
        )
        .to_list(length=None)
    )
    return logs


@router.get(
    "/logs/preprocessing",
    response_description="All preprocessing task logs retrieved",
    description="Retrieves detailed information about all preprocessing logs, including their statuses, options, task IDs, modification timestamps, source, target, and input format details."

)
async def get_all_preprocessing_logs(request: Request) -> list:
    logs = (
        await request.app.log["preprocessings"]
        .aggregate(
            [
                {
                    "$project": {
                        "_id": 0,
                        "options": 1,
                        "status": 1,
                        "tid": 1,
                        "modified": 1,
                        "source": 1,
                        "target": 1,
                        "input_format": 1,
                    },
                },
            ]
        )
        .to_list(length=None)
    )
    return logs


@router.get(
    "/logs/scan/{task_id}",
    response_description="All scan task logs retrieved",
    description="Retrieves detailed information about a specific task log identified by its task ID, including options, collection name, status, task ID, input details, total count, finished status, elapsed time, and modification timestamp."
)
async def get_task_log(request: Request, task_id: str) -> list:
    logs = (
        await request.app.log["tasks"]
        .aggregate(
            [
                {
                    "$match": {"tid": task_id},
                },
                {
                    "$project": {
                        "_id": 0,
                        "options": 1,
                        "collection": 1,
                        "status": 1,
                        "tid": 1,
                        "input": 1,
                        "total": 1,
                        "finished": 1,
                        "elapse": 1,
                        "modified": 1,
                    },
                },
            ]
        )
        .to_list(length=None)
    )
    return logs


@router.get(
    "/logs/report/{task_id}",
    response_description="All report task logs retrieved",
    description="Retrieves detailed information about a specific report log identified by its task ID, including options, collection name, status, task ID, external input, file ID, filename, and modification timestamp."

)
async def get_report_log(request: Request, task_id: str) -> list:
    logs = (
        await request.app.log["reports"]
        .aggregate(
            [
                {
                    "$match": {"tid": task_id},
                },
                {
                    "$project": {
                        "_id": 0,
                        "options": 1,
                        "metadata": 1,
                        "collection": 1,
                        "status": 1,
                        "tid": 1,
                        "external_input": 1,
                        "file_id": 1,
                        "filename": 1,
                        "modified": 1,
                    },
                },
            ]
        )
        .to_list(length=None)
    )
    return logs


@router.get(
    "/logs/outlier/{task_id}",
    response_description="All outlier detection task logs retrieved",
    description="Retrieves detailed information about a specific outlier detection log identified by its task ID, including options, collection name, status, task ID, and modification timestamp."

)
async def get_outlier_log(request: Request, task_id: str) -> list:
    logs = (
        await request.app.log["outliers"]
        .aggregate(
            [
                {
                    "$match": {"tid": task_id},
                },
                {
                    "$project": {
                        "_id": 0,
                        "options": 1,
                        "collection": 1,
                        "status": 1,
                        "tid": 1,
                        "modified": 1,
                    },
                },
            ]
        )
        .to_list(length=None)
    )
    return logs


@router.get(
    "/logs/preprocessing/{task_id}",
    response_description="All preprocessing task logs retrieved",
    description="Retrieves detailed information about a specific preprocessing log identified by its task ID, including options, status, task ID, modification timestamp, source, target, and input format."

)
async def get_preprocessing_log(request: Request, task_id: str) -> list:
    logs = (
        await request.app.log["preprocessings"]
        .aggregate(
            [
                {
                    "$match": {"tid": task_id},
                },
                {
                    "$project": {
                        "_id": 0,
                        "options": 1,
                        "status": 1,
                        "tid": 1,
                        "modified": 1,
                        "source": 1,
                        "target": 1,
                        "input_format": 1,
                    },
                },
            ]
        )
        .to_list(length=None)
    )
    return logs


@router.get("/{task_id}/status", response_description="Task status retrieved",description="Retrieves the status of a specific task identified by its task ID."
)
async def get_task_status(
    request: Request,
    task_id: UUID,
) -> dict:
    rds = request.app.queue
    if not await rds.exists(str(task_id)):
        raise HTTPException(status_code=404, detail="Task not found!")
    return json.loads(await rds.get(str(task_id)))


# @router.put("/{task_id}/", response_description="Task log retrieved")
# async def update_task_log(task_id: UUID, edit: EditTaskLog) -> TaskLog:
#     edit = {k: v for k, v in edit.dict().items() if v is not None}
#     edit_query = {"$set": {field: value for field, value in edit.items()}}
#     log = await TaskLog.find_one(TaskLog.tid == str(task_id))
#     if not log:
#         raise HTTPException(status_code=404, detail="Task log not found!")
#     await log.update(edit_query)
#     return log


@router.delete(
    "/{task_id}",
    response_description="Task log removed",
    description="Deletes a task log identified by its task ID, including removing it from the task queue in Redis.",
)
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


# @router.post("/reload", response_description="Task queue reloaded")
# async def reload_task(request: Request) -> dict:
#     logs = await TaskLog.find(TaskLog.status != Status.done).to_list(length=None)
#     queue = request.app.queue
#     for log in logs:
#         await queue.lpush("task_queue", log.tid)
#         if not await queue.exists(log.tid):
#             await queue.set(
#                 str(log.tid),
#                 json.dumps(
#                     TaskQueue(
#                         total=len(log.input),
#                         done=len(log.finished),
#                         eta=0
#                     ).dict()
#                 )
#             )
#     return {"message": "Successful, task queue reloaded from logs."}


@router.get("/queue", response_description="Task queue retrieved",description="Retrieves the current task queue stored in Redis as a list."
)
async def get_queue(request: Request) -> list:
    queue = request.app.queue
    queue = await queue.lrange("task_queue", 0, -1)
    return queue


@router.delete("/queue", response_description="Task queue cleared",description="Clears all tasks from the task queue stored in Redis."
)
async def clear_queue(request: Request):
    queue = request.app.queue
    tasks = await queue.lrange("task_queue", 0, -1)
    for item in tasks:
        await queue.delete(item)
    await queue.delete("task_queue")
    return {"message": "Successful, task queue cleared."}


@router.post("/queue/push", response_description="Task queue item appended")
async def push_queue_item(request: Request, tid: UUID) -> dict:
    queue = request.app.queue
    await queue.lpush("task_queue", str(tid))
    return {"message": "Successful, task queue item appended."}


@router.post("/queue/pop", response_description="Task queue item released")
async def pop_queue_item(request: Request) -> dict:
    queue = request.app.queue
    item = await queue.rpop("task_queue")
    return item


# @router.post("/test", response_description="BQAT core tests initiated")
# async def run_tests():
#     return await run_test_tasks()


@router.post(
    "/cancel/{task_id}",
    response_description="Task canceled",
    description="Cancels all tasks of a specified type (scan, report, outlier, preprocessing) with a given task ID, removing them from the task queue and cancelling any associated tasks.",
)
async def cancel_task(
    request: Request,
    task_id: str,
    type: str,
):
    queue = request.app.queue
    cache = request.app.cache

    while await queue.llen("task_queue") > 0:
        tid = await queue.rpop("task_queue")
        await queue.delete(tid)

    match type:
        case "scan":
            log = await TaskLog.find_one(TaskLog.tid == task_id)
        case "report":
            log = await ReportLog.find_one(ReportLog.tid == task_id)
        case "outlier":
            log = await OutlierDetectionLog.find_one(TaskLog.tid == task_id)
        case "preprocessing":
            log = await PreprocessingLog.find_one(TaskLog.tid == task_id)
        case _:
            raise HTTPException(status_code=400, detail="Task type not recognised!")

    if not log:
        # ray.shutdown()
        raise HTTPException(status_code=404, detail="Task not found!")
    elif not (task_refs := await cache.lrange("task_refs", 0, -1)):
        return {"message": "No tasks is running!"}
    else:
        for task in task_refs:
            try:
                ray.cancel(pickle.loads(task))
            except TypeError as e:
                # print(f"Task not found: {str(e)}")
                pass
            except Exception as e:
                print(f"Failed to cancel task: {str(e)}")

    await cache.ltrim("task_refs", 1, 0)
    await log.delete()


@router.post(
    "/cancel",
    response_description="All tasks cancelled",
    description="Cancels and clears all tasks in the task queue, including scanning, reporting, outlier detection, and preprocessing tasks, and returns the number of tasks aborted.",
)
async def cancel_all_tasks(
    request: Request,
):
    queue = request.app.queue
    cache = request.app.cache

    while await queue.llen("task_queue") > 0:
        tid = await queue.rpop("task_queue")
        await queue.delete(tid)

    task_result = await TaskLog.find(TaskLog.status == Status.running).delete()
    report_result = await ReportLog.find(ReportLog.status == Status.running).delete()
    outlier_result = await OutlierDetectionLog.find(
        OutlierDetectionLog.status == Status.running
    ).delete()
    preprocessing_result = await PreprocessingLog.find(
        PreprocessingLog.status == Status.running
    ).delete()

    for task in await cache.lrange("task_refs", 0, -1):
        try:
            ray.cancel(pickle.loads(task))
        except TypeError as e:
            # print(f"Task not found: {str(e)}")
            pass
        except Exception as e:
            print(f"Failed to cancel ray task: {str(e)}")

    return {
        "Tasks cancelled": f"{task_result.deleted_count + report_result.deleted_count + outlier_result.deleted_count + preprocessing_result.deleted_count}"
    }


@router.get(
    "/metadata",
    response_description="Metadata of pending tasks retrieved",
    description="Returns information about pending tasks.",
)
async def get_pending_tasks():
    if log := await TaskLog.find_one(TaskLog.status == Status.running):
        log = dict(log)
        log["type"] = "scan"
    elif log := await ReportLog.find_one(ReportLog.task_refs == Status.running):
        log = dict(log)
        log["type"] = "report"
    elif log := await OutlierDetectionLog.find_one(
        OutlierDetectionLog.task_refs == Status.running
    ):
        log = dict(log)
        log["type"] = "outlier"
    elif log := await PreprocessingLog.find_one(
        PreprocessingLog.task_refs == Status.running
    ):
        log = dict(log)
        log["type"] = "preprocessing"
    else:
        return {}

    log.pop("id")
    log.pop("revision_id")
    return log


@router.post(
    "/report/start",
    response_description="Report task queue resumed",
    description="Starts processing pending report tasks in the queue by initiating background tasks to run report generation."

)
async def start_report_queue(
    request: Request,
    background_tasks: BackgroundTasks,
):
    if (
        await request.app.log["reports"]
        .find(ReportLog.status != 2)
        .to_list(length=None)
    ):
        background_tasks.add_task(
            run_report_tasks,
            request.app.scan,
            request.app.log,
            request.app.queue,
            request.app.cache,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"message": "Successful, report queue started."},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report queue is empty"
        )


@router.post(
    "/outlier/start",
    response_description="Outlier detection task queue resumed",
    description="Starts processing pending outlier detection tasks in the queue by initiating background tasks to run outlier detection."

)
async def start_outlier_queue(
    request: Request,
    background_tasks: BackgroundTasks,
):
    if (
        await request.app.log["outliers"]
        .find(OutlierDetectionLog.status != 2)
        .to_list(length=None)
    ):
        background_tasks.add_task(
            run_outlier_detection_tasks,
            request.app.scan,
            request.app.log,
            request.app.queue,
            request.app.cache,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"message": "Successful, outlier queue started."},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outlier detection queue is empty",
        )


@router.post(
    "/preprocessing/start",
    response_description="Preprocessing task queue resumed",
    description="Starts processing pending preprocessing tasks in the queue by initiating background tasks to run preprocessing."
)
async def start_preprocessing_queue(
    request: Request,
    background_tasks: BackgroundTasks,
):
    if (
        await request.app.log["preprocessings"]
        .find(PreprocessingLog.status != 2)
        .to_list(length=None)
    ):
        background_tasks.add_task(
            run_preprocessing_tasks,
            request.app.log,
            request.app.queue,
            request.app.cache,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"message": "Successful, preprocessing queue started."},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preprocessing queue is empty",
        )


@router.get(
    "/inputs/metadata",
    response_description="Input folder metadata retrieved",
)
async def get_input_folder_metadata(
    exts: list[str] = Query(
        ["jpg", "jpeg", "png", "bmp", "wsq", "jp2", "wav"],
        description="File extensions to search for.",
    ),
    pattern: str = Query(
        "",
        description="Filename patterns to search for.",
    ),
    path: Path = Query(
        f"{Settings().DATA}",
        description="Directory to search for files.",
    ),
) -> dict[str, Union[int, Path]]:
    """Returns a list of folders in the input data folder.

    Args:
    - **exts (list[str], optional)**: File extensions as list.
    - **pattern (str, optional)**: Filename pattern regex string.
    - **path (Path, optional)**: Directory to search for files.

    Returns:

    ```json
        {
            "dir": "data/helen",
            "count": 2898,
        }
    ```
    """
    return {
        "dir": path.as_posix(),
        "count": len(
            [
                item
                for item in path.rglob("*")
                if item.is_file()
                and (pattern == "" or item.match(f"{pattern}{item.suffix}"))
                and len(item.suffix.lower().split(".")) == 2
                and item.suffix.lower().split(".")[1] in exts
            ]
        ),
    }


@router.get(
    "/inputs/folders",
    response_description="Input folders retrieved",
)
async def get_input_folders() -> list[str]:
    """Returns a list of folders in the input data directory.

    Returns:

    ```json
    [
        "data/helen",
        "data/bob",
    ]
    ```
    """
    return [dir.as_posix() for dir in Path(Settings().DATA).rglob("*") if dir.is_dir()]
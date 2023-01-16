import os
import json

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, status, File, UploadFile
from fastapi.responses import JSONResponse, HTMLResponse

from api.config.models import Metadata, ScanEdit, TaskLog, ScanTask, Modality, ReportLog
from api.utils import edit_attributes, run_scan_tasks, run_report_tasks, get_files, check_options, retrieve_report, remove_report

from typing import Union

router = APIRouter()


@router.post(
    "/",
    response_description="Add new scan tasks",
    status_code=status.HTTP_201_CREATED
)
async def scan(
    background_tasks: BackgroundTasks,
    request: Request,
    modality: Modality,
    tasks: ScanTask = Body(...),
):
    tasks = tasks.dict()
    if not modality:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"please specify biometric modality",
        )

    collection = tasks.get("collection")
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"please specify target collection of MongoDB in request body",
        )

    if not (options := tasks.get("options")):
        options = {} 
    if not (options := check_options(options, modality)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"modality not support",
        )
    
    input = tasks.get("input")
    if isinstance(input, str):
        if not os.path.exists(input):
            raise ValueError(f"folder '{input}' not exist")
        if not os.path.isdir(input):
            raise ValueError(f"path to '{input}' is not a folder")
        if extension := options.get("extension"):
            files = get_files(input, extension)
        else:
            files = get_files(input)
    elif isinstance(input, list):
        for v in input:
            if not os.path.exists(v):
                raise ValueError(f"file '{v}' not exist")
        files = input
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"illegal input",
        )

    task_log = TaskLog(collection=collection, input=files, options=options)
    task = await task_log.create()

    db = request.app.scan
    log = request.app.log
    queue = request.app.queue
    background_tasks.add_task(run_scan_tasks, db, log, queue)

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


# @router.post(
#     "/uploaded",
#     response_description="Add new scan tasks from uploaded file",
#     status_code=status.HTTP_201_CREATED
# )
# async def scan_uploaded(
#     file: UploadFile,
#     background_tasks: BackgroundTasks,
#     request: Request,
#     modality: Modality,
#     tasks: ScanTask = Body(...),
# ):


@router.get(
    "/logs",
    response_description="All scan log retrieved"
)
async def get_logs(request: Request) -> list:
    logs = []
    for doc in await request.app.log["dataset"].find().to_list(length=None):
        doc.pop("_id")
        logs.append(doc)
    return logs


@router.get(
    "/logs/{dataset_id}",
    response_description="Dataset scan log retrieved"
)
async def get_log(dataset_id: str, request: Request):
    if (
        doc := await request.app.log["dataset"].find_one({"collection": dataset_id})
    ) is not None:
        doc.pop("_id")
        return doc
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan log of [{dataset_id}] not found",
        )


@router.delete(
    "/logs/{dataset_id}",
    response_description="Dataset scan log deleted"
)
async def delete_log(dataset_id: str, request: Request):
    delete_result = await request.app.log["dataset"].delete_one({"collection": dataset_id})
    if delete_result.deleted_count > 0:
        return {"info": f"Scan log of [{dataset_id}] deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan log of [{dataset_id}] not found"
        )


@router.get(
    "/{dataset_id}/profiles",
    response_description="All image profiles for this dataset retrieved",
)
async def retrieve_all(dataset_id: str, request: Request):
    profiles = []
    for doc in await request.app.scan[dataset_id].find().to_list(length=None):
        doc.pop("_id")
        profiles.append(doc)
    return profiles


@router.delete(
    "/{dataset_id}/profiles",
    response_description="All image profiles for this dataset deleted",
)
async def delete_all(dataset_id: str, request: Request):
    res = await request.app.scan.drop_collection(dataset_id)
    return res


@router.get(
    "/{dataset_id}/profiles/{scan_id}",
    response_description="Image profile retrieved"
)
async def retrieve_one(dataset_id: str, scan_id: str, request: Request):
    if (
        doc := await request.app.scan[dataset_id].find_one({"uuid": scan_id})
    ) is not None:
        profile = doc.pop("_id")
        return profile
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image profile of [{scan_id}] not found",
        )


@router.put(
    "/{dataset_id}/profiles/{scan_id}",
    response_description="Image profile updated"
)
async def edit_one(
    dataset_id: str, scan_id: str, request: Request, edit: ScanEdit = Body(...)
):
    if (
        doc := await request.app.scan[dataset_id].find_one({"uuid": scan_id})
    ) is not None:
        doc.pop("_id")
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image profile [{scan_id}] not found",
        )
    attr = edit_attributes(doc, {k: v for k, v in edit.dict().items()})
    if attr:
        update_result = await request.app.scan[dataset_id].update_one(
            {"uuid": scan_id}, {"$set": attr}
        )
        if update_result.modified_count > 0:
            return {"info": f"Image profile [{scan_id}] edited"}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Image profile [{scan_id}] not found",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Bad attributes passed"
        )


@router.delete(
    "/{dataset_id}/profiles/{scan_id}",
    response_description="Image profile deleted",
)
async def delete_one(dataset_id: str, scan_id: str, request: Request):
    delete_result = await request.app.scan[dataset_id].delete_one({"uuid": scan_id})
    if delete_result.deleted_count > 0:
        return {"info": f"Image profile [{scan_id}] deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Image profile [{scan_id}] not found"
        )


@router.post(
    "/{dataset_id}/report",
    response_description="Report generation task added",
    status_code=status.HTTP_201_CREATED
)
async def generate_report(
    background_tasks: BackgroundTasks,
    dataset_id: str,
    request: Request,
    report_log: Union[ReportLog, None] = None 
):
    if not report_log:
        report_log = ReportLog(collection=dataset_id)
    task = await report_log.create()

    scan = request.app.scan
    log = request.app.log
    background_tasks.add_task(run_report_tasks, scan, log)
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"report task": str(task.collection)}
    )


@router.get(
    "/{dataset_id}/report",
    response_description="Report retrieved",
    response_class=HTMLResponse,
)
async def get_report(dataset_id: str, request: Request):
    if (
        doc := await request.app.log["report"].find_one({"collection": dataset_id})
    ) is not None:
        file_id = doc["file_id"]
        html_content = await retrieve_report(file_id, request.app.log)
        return HTMLResponse(content=html_content, status_code=200)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report of [{dataset_id}] not found",
        )


@router.delete(
    "/{dataset_id}/report",
    response_description="Dataset report deleted",
)
async def delete_report(dataset_id: str, request: Request):
    doc = await request.app.log["report"].find_one_and_delete({"collection": dataset_id})
    if doc:
        await remove_report(doc["file_id"], request.app.log)
        return {"info": f"Report of [{dataset_id}] deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Report of [{dataset_id}] not found"
        )


@router.post(
    "/{dataset_id}/rerun/{scan_id}",
    response_description="Image rescanned",
    status_code=status.HTTP_202_ACCEPTED
)
async def rescan_one(
    dataset_id: str,
    scan_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    face: bool = True,
    head: bool = True,
    quality: bool = True,
    confidence: float = 0.7,
):
    db = request.app.scan
    log = request.app.log
    queue = request.app.queue

    if (doc := await db[dataset_id].find_one({"uuid": scan_id})) is not None:
        file = doc.get("file")
        await db[dataset_id].delete_one({"uuid": scan_id})
        options = Options(face=face, head=head, quality=quality, confidence=confidence)
        task_log = TaskLog(collection=dataset_id, input=[file], options=options)
        task = await task_log.create()
        background_tasks.add_task(run_scan_tasks, db, log, queue)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED, content={"tid": str(task.tid)}
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Image profile [{scan_id}] not found"
        )


@router.post("/{dataset_id}/upload", response_description="Existing image profile uploaded")
async def upload_item(dataset_id: str, request: Request, meta: Metadata = Body(...)):
    metadata = meta.dict().get("metadata")
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image profile to upload not found",
        )
    await request.app.scan[dataset_id].insert_one(metadata)

    upload_result = await request.app.log["dataset"].update_one(
        {"collection": dataset_id}, {"$push": metadata['file']}
    )
    if upload_result.modified_count > 0:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"message": f"Image profile of [{metadata.get('file')}] uploaded"}
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan metadata of [{dataset_id}] not found",
        )


@router.get("/status", response_description="Scan task status retrieved")
async def get_status(request: Request):
    log = request.app.log
    tasks = await log["task"].find({"status": {"$lt": 2}}).to_list(length=None)
    if len(tasks) > 0:
        queue = request.app.queue
        task_queue = await queue.lrange("task_queue", 0, -1)
        if task_queue:
            in_progress = []
            for task in task_queue:
                queue_item = await queue.get(task)
                if queue_item is not None:
                    task_status = {"tid": task}
                    task_status.update(json.loads(queue_item))
                    in_progress.append(task_status)
            return {"status": f"[{len(tasks)}] tasks queuing", "tasks": in_progress}
        else:
            return {
                "status": f"[{len(tasks)}] tasks pending",
            }
    else:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED, content={"status": "No task in the queue"}
        )


@router.post("/pause", response_description="Task queue Paused")
async def pause_queue(request: Request):
    queue = request.app.queue
    await queue.delete("task_queue")
    await queue.delete("scan_queue")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED, content={"message": "Successful, task queue paused."}
    )


@router.post("/resume", response_description="Task queue resumed")
async def resume_queue(request: Request, background_tasks: BackgroundTasks):
    db = request.app.scan
    log = request.app.log
    queue = request.app.queue
    if len(await log["task"].find({"status": {"$lt": 2}}).to_list(length=None)) > 0:
        background_tasks.add_task(run_scan_tasks, db, log, queue)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED, content={"message": "Successful, task queue resumed."}
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task queue is empty"
        )


@router.post("/clear", response_description="Task queue stopped and cleared")
async def clear_queue(request: Request):
    queue = request.app.queue
    queue.delete("scan_queue")
    log = request.app.log
    while queue.llen("task_queue") > 0:
        tid = queue.rpop("task_queue")
        queue.delete(tid)
        await log["task"].delete_one({"tid": tid})
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": "Task queue cleared"}
    )

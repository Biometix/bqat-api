import os
import json

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, status, UploadFile
from fastapi.responses import JSONResponse, HTMLResponse

from api.config.models import ScanEdit, TaskLog, ScanTask, Modality, ReportLog, SampleLog
from api.utils import edit_attributes, run_scan_tasks, run_report_tasks, get_files, check_options, retrieve_report, remove_report, get_info

from typing import List
from beanie.odm.operators.update.general import Set
import uuid

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
        if extension := options.get("extension"):
            files = get_files(input, extension)
        else:
            files = get_files(input)
    elif isinstance(input, list):
        files = input
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"illegal input",
        )

    task = await TaskLog(
        collection=collection,
        input=len(files), 
        options=options
    ).create()

    samples = [
        SampleLog(
            tid=str(task.tid),
            collection=str(task.collection),
            path=file
        )
        for file in files
    ]
    await SampleLog.insert_many(samples)

    background_tasks.add_task(
        run_scan_tasks,
        request.app.scan,
        request.app.log,
        request.app.queue
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


@router.post(
    "/uploaded",
    response_description="Add new scan tasks from uploaded file",
    status_code=status.HTTP_201_CREATED
)
async def scan_uploaded(
    files: List[UploadFile],
    background_tasks: BackgroundTasks,
    request: Request,
    modality: Modality,
):
    if not modality:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"please specify biometric modality",
        )
    
    tmp = "data/tmp/"
    if not os.path.exists(tmp): os.mkdir(tmp)
    for file in files:
        with open(f"data/tmp/{file.filename}", "wb") as out:
            data = await file.read()
            out.write(data)

    files = get_files(tmp)
    task = await TaskLog(
        collection=uuid.uuid4(),
        input=len(files), 
        options={"mode": modality, "uploaded": True}
    ).create()

    samples = [
        SampleLog(
            tid=str(task.tid),
            collection=str(task.collection),
            path=file
        )
        for file in files
    ]
    await SampleLog.insert_many(samples)

    background_tasks.add_task(
        run_scan_tasks,
        request.app.scan,
        request.app.log,
        request.app.queue
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


@router.get(
    "/logs",
    response_description="All scan log retrieved"
)
async def get_logs(request: Request) -> list:
    logs = []
    for doc in await request.app.log["datasets"].find().to_list(length=None):
        doc.pop("_id")
        logs.append(doc)
    return logs


@router.get(
    "/logs/{dataset_id}",
    response_description="Dataset scan log retrieved"
)
async def get_log(dataset_id: str, request: Request):
    if (
        doc := await request.app.log["datasets"].find_one({"collection": dataset_id})
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
    delete_result = await request.app.log["datasets"].delete_one({"collection": dataset_id})
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
    "/{dataset_id}/report/generate",
    response_description="Report generation task added",
    status_code=status.HTTP_202_ACCEPTED
)
async def generate_report(
    background_tasks: BackgroundTasks,
    dataset_id: str,
    request: Request,
    options: dict = {}
):
    found = await ReportLog.find_one(ReportLog.collection == dataset_id)
    await ReportLog.find_one(ReportLog.collection == dataset_id).upsert(
        Set({
            ReportLog.minimal: options.get("minimal", False),
            ReportLog.downsample: options.get("downsample", False),
            ReportLog.file_id: None,
            ReportLog.filename: None,
        }),
        on_insert=ReportLog(collection=dataset_id, **options)
    )

    if found and found.file_id:
        await remove_report(found.file_id, request.app.log)

    background_tasks.add_task(
        run_report_tasks,
        request.app.scan,
        request.app.log
    )
    
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED, content={"reporting in progress": dataset_id}
    )


@router.get(
    "/{dataset_id}/report",
    response_description="Report retrieved",
    response_class=HTMLResponse,
)
async def get_report(dataset_id: str, request: Request):
    if (
        doc := await request.app.log["reports"].find_one({"collection": dataset_id})
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
    doc = await request.app.log["reports"].find_one_and_delete({"collection": dataset_id})
    if doc:
        await remove_report(doc["file_id"], request.app.log)
        return {"info": f"Report of [{dataset_id}] deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Report of [{dataset_id}] not found"
        )


# @router.post(
#     "/{dataset_id}/rerun/{scan_id}",
#     response_description="Image rescanned",
#     status_code=status.HTTP_202_ACCEPTED
# )
# async def rescan_one(
#     dataset_id: str,
#     scan_id: str,
#     background_tasks: BackgroundTasks,
#     request: Request,
#     face: bool = True,
#     head: bool = True,
#     quality: bool = True,
#     confidence: float = 0.7,
# ):
#     db = request.app.scan
#     log = request.app.log
#     queue = request.app.queue

#     if (doc := await db[dataset_id].find_one({"uuid": scan_id})) is not None:
#         file = doc.get("file")
#         await db[dataset_id].delete_one({"uuid": scan_id})
#         options = Options(face=face, head=head, quality=quality, confidence=confidence)
#         task_log = TaskLog(collection=dataset_id, input=[file], options=options)
#         task = await task_log.create()
#         background_tasks.add_task(run_scan_tasks, db, log, queue)
#         return JSONResponse(
#             status_code=status.HTTP_202_ACCEPTED, content={"tid": str(task.tid)}
#         )
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND, detail=f"Image profile [{scan_id}] not found"
#         )


# @router.post("/{dataset_id}/upload", response_description="Existing image profile uploaded")
# async def upload_item(dataset_id: str, request: Request, meta: Metadata = Body(...)):
#     metadata = meta.dict().get("metadata")
#     if not metadata:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Image profile to upload not found",
#         )
#     await request.app.scan[dataset_id].insert_one(metadata)

#     upload_result = await request.app.log["datasets"].update_one(
#         {"collection": dataset_id}, {"$push": metadata['file']}
#     )
#     if upload_result.modified_count > 0:
#         return JSONResponse(
#             status_code=status.HTTP_202_ACCEPTED,
#             content={"message": f"Image profile of [{metadata.get('file')}] uploaded"}
#         )
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Scan metadata of [{dataset_id}] not found",
#         )


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


# @router.post("/pause", response_description="Task queue Paused")
# async def pause_queue(request: Request):
#     queue = request.app.queue
#     await queue.delete("task_queue")
#     await queue.delete("scan_queue")
#     return JSONResponse(
#         status_code=status.HTTP_202_ACCEPTED, content={"message": "Successful, task queue paused."}
#     )


# @router.post("/resume", response_description="Task queue resumed")
# async def resume_queue(request: Request, background_tasks: BackgroundTasks):
#     if len(await request.app.log["tasks"].find({"status": {"$lt": 2}}).to_list(length=None)) > 0:
#         background_tasks.add_task(
#             run_scan_tasks,
#             request.app.scan,
#             request.app.log,
#             request.app.queue
#         )
#         return JSONResponse(
#             status_code=status.HTTP_202_ACCEPTED, content={"message": "Successful, task queue resumed."}
#         )
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND, detail="Task queue is empty"
#         )


@router.post("/clear", response_description="Task queue stopped and cleared")
async def clear_queue(request: Request):
    queue = request.app.queue
    queue.delete("scan_queue")
    log = request.app.log
    while queue.llen("task_queue") > 0:
        tid = queue.rpop("task_queue")
        queue.delete(tid)
        await log["tasks"].delete_one({"tid": tid})
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": "Task queue cleared"}
    )


@router.get("/info", response_description="BQAT backend info retrieved")
async def info():
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=get_info()
    )

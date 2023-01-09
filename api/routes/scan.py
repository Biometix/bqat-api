import json

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, status
from fastapi.responses import JSONResponse

from api.config.models import FileList, Folder, Metadata, Options, ScanEdit, TaskLog
from api.utils import edit_attributes, run_tasks, get_files

router = APIRouter()


@router.post(
    "/folder",
    response_description="Add new scan tasks from a folder",
    status_code=status.HTTP_201_CREATED
)
async def scan_folder(
    background_tasks: BackgroundTasks,
    request: Request,
    tasks: Folder = Body(...),
    face: bool = True,
    head: bool = True,
    quality: bool = True,
    confidence: float = 0.7,
):
    folder_path = tasks.dict().get("path")
    if not folder_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"please include folder path in request body",
        )
    files = get_files(folder_path)
    collection = tasks.dict().get("collection")
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"please include target collection of MongoDB in request body",
        )
    options = Options(face=face, head=head, quality=quality, confidence=confidence)
    task_log = TaskLog(collection=collection, input=files, options=options)
    task = await task_log.create()

    db = request.app.scan
    log = request.app.log
    queue = request.app.queue
    background_tasks.add_task(run_tasks, db, log, queue)

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


@router.post(
    "/files",
    response_description="Add new scan task from a list of files",
    status_code=status.HTTP_201_CREATED
)
async def scan_files(
    background_tasks: BackgroundTasks,
    request: Request,
    tasks: FileList = Body(...),
    face: bool = True,
    head: bool = True,
    quality: bool = True,
    confidence: float = 0.7,
):
    files = list(tasks.dict().get("files"))
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"please include file path in request body",
        )
    collection = tasks.dict().get("collection")
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"please include target collection of MongoDB in request body",
        )
    options = Options(face=face, head=head, quality=quality, confidence=confidence)
    task_log = TaskLog(collection=collection, input=files, options=options)
    task = await task_log.create()

    db = request.app.scan
    log = request.app.log
    queue = request.app.queue
    background_tasks.add_task(run_tasks, db, log, queue)

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


@router.get(
    "/metadata/all",
    response_description="All scan metadata retrieved"
)
async def get_metadata_all(request: Request) -> list:
    logs = []
    for doc in await request.app.log["dataset"].find().to_list(length=None):
        doc.pop("_id")
        logs.append(doc)
    return logs


@router.get(
    "/metadata/{dataset_id}",
    response_description="Scan metadata of the dataset retrieved"
)
async def get_metadata(dataset_id: str, request: Request):
    if (
        doc := await request.app.log["dataset"].find_one({"collection": dataset_id})
    ) is not None:
        doc.pop("_id")
        return doc
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan metadata of [{dataset_id}] not found",
        )


@router.delete(
    "/metadata/{dataset_id}",
    response_description="Scan metadata of the dataset deleted"
)
async def delete_metadata(dataset_id: str, request: Request):
    delete_result = await request.app.log["dataset"].delete_one({"collection": dataset_id})
    if delete_result.deleted_count > 0:
        return {"info": f"Scan metadata of [{dataset_id}] deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan metadata of [{dataset_id}] not found"
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
        background_tasks.add_task(run_tasks, db, log, queue)
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
        background_tasks.add_task(run_tasks, db, log, queue)
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

import json
import os
import uuid
from typing import List

from beanie.odm.operators.update.general import Set
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse

from api.config import Settings
from api.config.models import (
    Modality,
    ReportLog,
    SampleLog,
    ScanEdit,
    ScanTask,
    TaskLog,
)
from api.utils import (
    DETECTORS,
    check_options,
    edit_attributes,
    get_files,
    get_info,
    get_tag,
    remove_report,
    retrieve_report,
    run_outlier_detection_tasks,
    run_report_tasks,
    run_scan_tasks,
)

router = APIRouter()


@router.post(
    "/", response_description="Add new scan tasks", status_code=status.HTTP_201_CREATED
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
            detail=f"modality not supported",
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

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"empty input",
        )

    task = await TaskLog(
        collection=collection, input=len(files), options=options
    ).create()

    samples = [
        SampleLog(tid=str(task.tid), collection=str(task.collection), path=file)
        for file in files
    ]
    await SampleLog.insert_many(samples)

    background_tasks.add_task(
        run_scan_tasks, request.app.scan, request.app.log, request.app.queue
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


@router.post(
    "/uploaded",
    response_description="Add new scan tasks from uploaded file",
    status_code=status.HTTP_201_CREATED,
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

    if not os.path.exists(Settings().TEMP):
        os.mkdir(Settings().TEMP)
    for file in files:
        with open(f"{Settings().TEMP}{file.filename}", "wb") as out:
            data = await file.read()
            out.write(data)

    files = get_files(Settings().TEMP)
    options = {"mode": modality, "uploaded": True}

    if modality == "speech" and not options.get("type"):
        options.update({"type": "file"})

    task = await TaskLog(
        collection=uuid.uuid4(),
        input=len(files),
        options=options,
    ).create()

    samples = [
        SampleLog(tid=str(task.tid), collection=str(task.collection), path=file)
        for file in files
    ]
    await SampleLog.insert_many(samples)

    background_tasks.add_task(
        run_scan_tasks, request.app.scan, request.app.log, request.app.queue
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


@router.get("/logs", response_description="All scan log retrieved")
async def get_logs(request: Request) -> list:
    logs = await request.app.log["datasets"].find({}, {"_id": 0}).to_list(length=None)
    return logs


@router.get("/logs/{dataset_id}", response_description="Dataset scan log retrieved")
async def get_log(dataset_id: str, request: Request):
    if (
        doc := await request.app.log["datasets"].find_one(
            {"collection": dataset_id}, {"_id": 0}
        )
    ) is not None:
        return doc
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan log of [{dataset_id}] not found",
        )


@router.delete("/logs/{dataset_id}", response_description="Dataset scan log deleted")
async def delete_log(dataset_id: str, request: Request):
    delete_result = await request.app.log["datasets"].delete_one(
        {"collection": dataset_id}
    )
    if delete_result.deleted_count > 0:
        return {"info": f"Scan log of [{dataset_id}] deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan log of [{dataset_id}] not found",
        )


@router.get(
    "/{dataset_id}/profiles",
    response_description="All image profiles for this dataset retrieved",
)
async def retrieve_all(dataset_id: str, request: Request):
    profiles = (
        await request.app.scan[dataset_id].find({}, {"_id": 0}).to_list(length=None)
    )
    return profiles


@router.delete(
    "/{dataset_id}/profiles",
    response_description="All image profiles for this dataset deleted",
)
async def delete_all(dataset_id: str, request: Request):
    res = await request.app.scan.drop_collection(dataset_id)
    return res


@router.get(
    "/{dataset_id}/profiles/{scan_id}", response_description="Image profile retrieved"
)
async def retrieve_one(dataset_id: str, scan_id: str, request: Request):
    if (
        doc := await request.app.scan[dataset_id].find_one({"tag": scan_id}, {"_id": 0})
    ) is not None:
        return doc
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image profile of [{scan_id}] not found",
        )


# @router.put(
#     "/{dataset_id}/profiles/{scan_id}",
#     response_description="Image profile updated"
# )
# async def edit_one(
#     dataset_id: str, scan_id: str, request: Request, edit: ScanEdit = Body(...)
# ):
#     if (
#         doc := await request.app.scan[dataset_id].find_one({"tag": scan_id})
#     ) is not None:
#         doc.pop("_id")
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Image profile [{scan_id}] not found",
#         )
#     attr = edit_attributes(doc, {k: v for k, v in edit.dict().items()})
#     if attr:
#         update_result = await request.app.scan[dataset_id].update_one(
#             {"tag": scan_id}, {"$set": attr}
#         )
#         if update_result.modified_count > 0:
#             return {"info": f"Image profile [{scan_id}] edited"}
#         else:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Image profile [{scan_id}] not found",
#             )
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST, detail=f"Bad attributes passed"
#         )


@router.delete(
    "/{dataset_id}/profiles/{scan_id}",
    response_description="Image profile deleted",
)
async def delete_one(dataset_id: str, scan_id: str, request: Request):
    delete_result = await request.app.scan[dataset_id].delete_one({"tag": scan_id})
    if delete_result.deleted_count > 0:
        return {"info": f"Image profile [{scan_id}] deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image profile [{scan_id}] not found",
        )


@router.get(
    "/detectors",
    response_description="Outlier detectors retrieved",
    status_code=status.HTTP_200_OK,
)
def get_detectors():
    return {"outlier detectors": DETECTORS}


@router.post(
    "/{dataset_id}/outliers/detect",
    response_description="Outlier detection task added",
    status_code=status.HTTP_202_ACCEPTED,
)
async def detect_outliers(
    background_tasks: BackgroundTasks,
    dataset_id: str,
    request: Request,
    options: dict = {},
):
    TARGET = {
        "fingerprint": [
            "NFIQ2",
            "UniformImage",
            "EmptyImageOrContrastTooLow",
            "EdgeStd",
        ],
        "face": ["confidence", "ipd", "yaw_degree", "pitch_degree", "roll_degree"],
        "iris": [
            "quality",
            "normalized_contrast",
            "normalized_iris_diameter",
            "normalized_iris_pupil_gs",
            "normalized_iris_sclera_gs",
            "normalized_percent_visible_iris",
            "normalized_sharpness",
        ],
    }

    if not options.get("columns"):
        try:
            if not (modality := options.get("modality")):
                doc = await request.app.log["datasets"].find_one(
                    {"collection": dataset_id}
                )
                modality = doc["options"]["mode"]
            options.update({"columns": TARGET[modality]})
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to retrieve target columns: {str(e)}",
            )

    background_tasks.add_task(
        run_outlier_detection_tasks,
        dataset_id,
        options,
        request.app.scan,
        request.app.log,
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"outlier detection task in progress": dataset_id},
    )


@router.get("/{dataset_id}/outliers", response_description="Outliers retrieved")
async def get_outliers(dataset_id: str, request: Request):
    if (
        outliers := await request.app.log["outliers"]
        .find({"collection": dataset_id}, {"_id": 0})
        .to_list(length=None)
    ):
        outliers = [get_tag(outlier["file"]) for outlier in outliers]
        profiles = (
            await request.app.scan[dataset_id]
            .find({"tag": {"$in": outliers}}, {"_id": 0})
            .to_list(length=None)
        )
    return profiles


@router.delete(
    "/{dataset_id}/outliers",
    response_description="Outliers deleted",
)
async def delete_outliers(dataset_id: str, request: Request):
    result = await request.app.log["outliers"].delete_many({"collection": dataset_id})
    if result.deleted_count > 0:
        return {"info": f"Outliers of [{dataset_id}] deleted: {result.deleted_count}"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outliers of [{dataset_id}] not found",
        )


@router.post(
    "/{dataset_id}/report/generate",
    response_description="Report generation task added",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_report(
    background_tasks: BackgroundTasks,
    dataset_id: str,
    request: Request,
    options: dict = {},
):
    found = await ReportLog.find_one(ReportLog.collection == dataset_id)
    await ReportLog.find_one(ReportLog.collection == dataset_id).upsert(
        Set(
            {
                ReportLog.minimal: options.get("minimal", False),
                ReportLog.downsample: options.get("downsample", False),
                ReportLog.file_id: None,
                ReportLog.filename: None,
            }
        ),
        on_insert=ReportLog(collection=dataset_id, **options),
    )

    if found and found.file_id:
        await remove_report(found.file_id, request.app.log)

    background_tasks.add_task(run_report_tasks, request.app.scan, request.app.log)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"reporting in progress": dataset_id},
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
    doc = await request.app.log["reports"].find_one_and_delete(
        {"collection": dataset_id}
    )
    if doc:
        await remove_report(doc["file_id"], request.app.log)
        return {"info": f"Report of [{dataset_id}] deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report of [{dataset_id}] not found",
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
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "No task in the queue"},
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
        status_code=status.HTTP_202_ACCEPTED, content={"message": "Task queue cleared"}
    )


@router.get("/info", response_description="BQAT backend info retrieved")
async def info():
    return JSONResponse(status_code=status.HTTP_200_OK, content=get_info())

import json
import os

# import pickle
import shutil
import uuid
from pathlib import Path
from typing import List

import ray
from beanie.odm.operators.update.general import Set
from beanie.odm.queries.update import UpdateResponse
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
    Detector,
    DetectorOptions,
    Engine,
    Modality,
    OutlierDetectionLog,
    PreprocessingLog,
    # PreprocessingOptions,
    ReportLog,
    ReportOptions,
    SampleLog,
    # ScanEdit,
    # ScanOptions,
    ScanTask,
    Status,
    TaskLog,
)
from api.utils import (
    check_options,
    # edit_attributes,
    get_files,
    # get_info,
    # get_tag,
    remove_report,
    retrieve_report,
    run_outlier_detection_tasks,
    run_preprocessing_tasks,
    run_report_tasks,
    run_scan_tasks,
    split_input_folder,
)

router = APIRouter()


@router.post(
    "/local",
    response_description="New task from local files created",
    status_code=status.HTTP_201_CREATED,
    description="Creates a new scan task using local files as input. The task is configured based on the provided modality and task options.",
)
async def post_local_task(
    request: Request,
    background_tasks: BackgroundTasks,
    modality: Modality,
    task: ScanTask = Body(...),
    trigger: bool = True,
):
    task = task.model_dump()
    if not modality:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="please specify biometric modality",
        )

    collection = task.get("collection")
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="please specify target collection of MongoDB in request body",
        )

    if not (options := task.get("options")):
        options = {}
    if not (options := check_options(options, modality)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task options error found",
        )

    # TODO add preprocessing step

    input = task.get("input")
    if isinstance(input, str):
        extension = options.get("source", ("jpg", "jpeg", "png", "bmp", "wsq", "jp2", "wav"))
        if extension is None:
            extension = ["jpg", "jpeg", "png", "bmp", "wsq", "jp2", "wav"]
        pattern = options.get("pattern")
        files = get_files(input, ext=extension, pattern=pattern)

    elif isinstance(input, list):
        files = input
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="illegal input",
        )

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty input",
        )

    task = await TaskLog(
        collection=collection, input=input, total=len(files), options=options
    ).create()

    if modality == "face" and options.get("engine") == "ofiq":
        temp_folder = Path(Settings().TEMP) / f"{task.tid}"
        if not temp_folder.exists():
            temp_folder.mkdir(parents=True, exist_ok=False)
        folders = split_input_folder(
            input_folder=input,
            temp_folder=str(temp_folder),
            batch_size=options.get("batch", 30) if options.get("batch") else 30,
        )
        samples = [
            SampleLog(tid=str(task.tid), collection=str(task.collection), path=folder)
            for folder in folders
        ]
        await SampleLog.insert_many(samples)
    elif modality == "speech" or options.get("type") == "folder":
        sample = SampleLog(
            tid=str(task.tid), collection=str(task.collection), path=input
        )
        await SampleLog.insert_one(sample)
    else:
        samples = [
            SampleLog(tid=str(task.tid), collection=str(task.collection), path=file)
            for file in files
        ]
        await SampleLog.insert_many(samples)

    if trigger:
        background_tasks.add_task(
            run_scan_tasks,
            request.app.scan,
            request.app.log,
            request.app.queue,
            request.app.cache,
            str(task.tid),
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


@router.post(
    "/remote",
    response_description="New tasks from remote files created",
    status_code=status.HTTP_201_CREATED,
    description=(
        "Creates a new scan task using uploaded files as input. "
        "The task is configured based on the provided modality and optional engine parameter. "
        "Files are temporarily stored on the server for processing."
    ),
)
async def post_remote_task(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile],
    modality: Modality,
    engine: str | None = None,
    trigger: bool = True,
):
    if not modality:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="please specify biometric modality",
        )

    tid = uuid.uuid4()
    temp_folder = Path(Settings().TEMP) / f"{tid}"
    if not temp_folder.exists():
        temp_folder.mkdir(parents=True, exist_ok=False)

    input = temp_folder / "input"
    input.mkdir(parents=True, exist_ok=False)
    for file in files:
        with open(input / f"{file.filename}", "wb") as out:
            data = await file.read()
            out.write(data)

    files = get_files(str(input))

    options = (
        {
            "engine": Engine(engine) if engine else Engine.bqat,
        }
        if modality == "face"
        else {}
    )

    options.update({"temp": True})

    if not (options := check_options(options, modality)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task options error found",
        )

    task = await TaskLog(
        tid=tid,
        collection=uuid.uuid4(),
        input=str(input),
        total=len(files),
        options=options,
    ).create()

    if modality == "face" and options.get("engine") == "ofiq":
        folders = split_input_folder(
            input_folder=str(input),
            temp_folder=str(temp_folder),
            batch_size=options.get("batch", 30) if options.get("batch") else 30,
        )
        samples = [
            SampleLog(tid=str(task.tid), collection=str(task.collection), path=folder)
            for folder in folders
        ]
        await SampleLog.insert_many(samples)
    elif modality == "speech" or options.get("type") == "folder":
        sample = SampleLog(
            tid=str(task.tid), collection=str(task.collection), path=str(input)
        )
        await SampleLog.insert_one(sample)
    else:
        samples = [
            SampleLog(tid=str(task.tid), collection=str(task.collection), path=file)
            for file in files
        ]
        await SampleLog.insert_many(samples)

    if trigger:
        background_tasks.add_task(
            run_scan_tasks,
            request.app.scan,
            request.app.log,
            request.app.queue,
            request.app.cache,
            str(task.tid),
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
    )


# @router.post(
#     "/remote/files",
#     response_description="New remote input tasks files uploaded",
#     status_code=status.HTTP_201_CREATED,
#     description=(
#         "Uploads files to the server, stores them temporarily, and creates a new task for processing. "
#         "The files are read and saved to a temporary folder. A new task is created in the task log "
#         "and each file is logged as a sample in the sample log."
#     ),
# )
# async def upload_remote_task_files(
#     files: List[UploadFile],
# ):
#     if not os.path.exists(Settings().TEMP):
#         os.mkdir(Settings().TEMP)
#     temp_folder = f"{Settings().TEMP}{uuid.uuid4()}/"
#     os.mkdir(temp_folder)
#     for file in files:
#         with open(f"{temp_folder}{file.filename}", "wb") as out:
#             data = await file.read()
#             out.write(data)

#     files = get_files(temp_folder)

#     # TODO add preprocessing step

#     task = await TaskLog(
#         collection=uuid.uuid4(),
#         input=temp_folder,
#         total=len(files),
#     ).create()

#     samples = [
#         SampleLog(tid=str(task.tid), collection=str(task.collection), path=file)
#         for file in files
#     ]
#     await SampleLog.insert_many(samples)

#     return JSONResponse(
#         status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
#     )


# @router.put(
#     "/remote/{task_id}",
#     response_description="New remote input task options uploaded",
#     status_code=status.HTTP_201_CREATED,
# )
# async def update_remote_task_options(
#     task_id: str,
#     modality: Modality,
#     options: ScanOptions = Body(...),
# ):
#     if not modality:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="please specify biometric modality",
#         )

#     task = await TaskLog.find_one(TaskLog.tid == task_id)
#     options.update({"temp": True})
#     task.options = options
#     await task.save()

#     return JSONResponse(
#         status_code=status.HTTP_200_OK,
#         content={"tid": str(task.tid)},
#     )


# @router.post(
#     "/",
#     response_description="Add new scan tasks",
#     status_code=status.HTTP_201_CREATED,
#     description=(
#         "Creates a new scan task using the specified modality and options. The task can be triggered immediately or added to a background task queue. "
#         "This endpoint supports various input types and configurations, and it logs each task and its associated samples."
#     ),
# )
# async def create_scan_task(
#     background_tasks: BackgroundTasks,
#     request: Request,
#     modality: Modality,
#     trigger: bool = True,
#     tasks: ScanTask = Body(...),
# ):
#     tasks = tasks.dict()
#     if not modality:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="please specify biometric modality",
#         )

#     collection = tasks.get("collection")
#     if not collection:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="please specify target collection of MongoDB in request body",
#         )

#     if not (options := tasks.get("options")):
#         options = {}
#     if not (options := check_options(options, modality)):
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="modality not supported",
#         )

#     input = tasks.get("input")
#     if isinstance(input, str):
#         if extension := options.get("source"):
#             files = get_files(input, extension)
#         else:
#             files = get_files(input)
#     elif isinstance(input, list):
#         files = input
#     else:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="illegal input",
#         )

#     if not files:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="empty input",
#         )

#     task = await TaskLog(
#         collection=collection, input=input, total=len(files), options=options
#     ).create()

#     if modality == "speech" or options.get("engine") == "ofiq":
#         sample = SampleLog(
#             tid=str(task.tid), collection=str(task.collection), path=input
#         )
#         await SampleLog.insert_one(sample)
#     else:
#         samples = [
#             SampleLog(tid=str(task.tid), collection=str(task.collection), path=file)
#             for file in files
#         ]
#         await SampleLog.insert_many(samples)

#     if trigger:
#         background_tasks.add_task(
#             run_scan_tasks,
#             request.app.scan,
#             request.app.log,
#             request.app.queue,
#         )

#     return JSONResponse(
#         status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
#     )


# @router.post(
#     "/uploaded",
#     response_description="Add new scan tasks from uploaded file",
#     status_code=status.HTTP_201_CREATED,
#     description=(
#         "Creates a new scan task using uploaded files, and based on the specified modality and options. "
#         "Files are saved temporarily on the server, and a new task is created in the task log. Each file is logged as a sample in the sample log. "
#         "The task can be triggered immediately or added to a background task queue for processing."
#     )
# )
# async def create_scan_task_uploaded(
#     files: List[UploadFile],
#     background_tasks: BackgroundTasks,
#     request: Request,
#     modality: Modality,
#     trigger: bool = True,
# ):
#     if not modality:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="please specify biometric modality",
#         )

#     if not os.path.exists(Settings().TEMP):
#         os.mkdir(Settings().TEMP)
#     for file in files:
#         with open(f"{Settings().TEMP}{file.filename}", "wb") as out:
#             data = await file.read()
#             out.write(data)

#     files = get_files(Settings().TEMP)
#     options = {"mode": modality, "uploaded": True}

#     if modality == "speech" and not options.get("type"):
#         options.update({"type": "file"})

#     task = await TaskLog(
#         collection=uuid.uuid4(),
#         input=len(files),
#         options=options,
#     ).create()

#     samples = [
#         SampleLog(tid=str(task.tid), collection=str(task.collection), path=file)
#         for file in files
#     ]
#     await SampleLog.insert_many(samples)

#     if trigger:
#         background_tasks.add_task(
#             run_scan_tasks,
#             request.app.scan,
#             request.app.log,
#             request.app.queue,
#         )

#     return JSONResponse(
#         status_code=status.HTTP_201_CREATED, content={"tid": str(task.tid)}
#     )


@router.get("/logs", response_description="All new task logs retrieved", description="Fetches logs of datasets from the server.")
async def get_logs(request: Request) -> list:
    logs = (
        await request.app.log["datasets"]
        .find(
            {},
            {
                "_id": 0,
            },
        )
        .to_list(length=None)
    )
    return logs


@router.get("/logs/{dataset_id}", response_description="Dataset scan log retrieved", description="Fetches details of a specific dataset log based on its ID.")
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


@router.delete("/logs/{dataset_id}", response_description="Dataset scan log deleted",description="Deletes a specific dataset log based on its ID.")
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
    description="Retrieves all image profiles associated with a specific dataset."
)
async def retrieve_all(
    dataset_id: str,
    request: Request,
    skip: int = 0,
    limit: int = 0,
):
    profiles = request.app.scan[dataset_id].find({}, {"_id": 0})
    if skip:
        profiles = profiles.skip(skip)
    if limit:
        profiles = profiles.limit(limit)
    return await profiles.to_list(length=None)


@router.delete(
    "/{dataset_id}/profiles",
    response_description="All image profiles for this dataset deleted",
    description="Deletes all image profiles associated with a specific dataset."
)
async def delete_all(dataset_id: str, request: Request):
    res = await request.app.scan.drop_collection(dataset_id)
    return res


@router.get(
    "/{dataset_id}/profiles/{scan_id}", response_description="Image profile retrieved",
    description="Retrieves a specific image profile from a dataset based on its scan ID."
)
async def retrieve_one(dataset_id: str, scan_id: str, request: Request):
    if (
        doc := await request.app.scan[dataset_id].find_one(
            {"tag": scan_id},
            {"_id": 0},
        )
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
    description="Deletes a specific image profile from a dataset based on its scan ID."

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
    description="Fetches a list of available outlier detectors."
)
def get_detectors():
    return {"Outlier detectors": list(Detector)}


@router.post(
    "/{dataset_id}/outliers/detect",
    response_description="Outlier detection task added",
    status_code=status.HTTP_202_ACCEPTED,
    description="Initiates outlier detection for a specified dataset based on provided options. Optionally triggers the detection task for processing."

)
async def detect_outliers(
    background_tasks: BackgroundTasks,
    dataset_id: str,
    request: Request,
    trigger: bool = True,
    options: DetectorOptions = Body(...),
):
    TARGET = {
        "fingerprint": [
            "NFIQ2",
            "UniformImage",
            "EmptyImageOrContrastTooLow",
            "SufficientFingerprintForeground",
            "EdgeStd",
        ],
        "face": [
            "confidence",
            "ipd",
            "yaw_degree",
            "pitch_degree",
            "roll_degree",
        ],
        "iris": [
            # "quality",
            # "normalized_contrast",
            # "normalized_iris_pupil_gs",
            # "normalized_iris_sclera_gs",
            # "normalized_percent_visible_iris",
            # "normalized_sharpness",
            "iso_overall_quality",
            "iso_sharpness",
            "iso_iris_sclera_contrast",
            "iso_iris_pupil_contrast",
            "iso_iris_pupil_concentricity",
        ],
    }

    if not options.columns or not len(options.columns):
        try:
            doc = await request.app.log["datasets"].find_one({"collection": dataset_id})
            modality = doc["options"]["mode"]
            options.columns = TARGET[modality]
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"failed to retrieve target columns: {str(e)}",
            )

    old_log = await OutlierDetectionLog.find_one(
        OutlierDetectionLog.collection == dataset_id
    )
    if old_log and old_log.outliers:
        await request.app.outlier[dataset_id].drop()

    log = await OutlierDetectionLog.find_one(
        OutlierDetectionLog.collection == dataset_id
    ).upsert(
        Set(
            {
                OutlierDetectionLog.options: options,
                OutlierDetectionLog.outliers: None,
            }
        ),
        on_insert=OutlierDetectionLog(
            collection=dataset_id,
            options=options,
        ),
        response_type=UpdateResponse.NEW_DOCUMENT,
    )

    if trigger:
        background_tasks.add_task(
            run_outlier_detection_tasks,
            request.app.scan,
            request.app.log,
            request.app.outlier,
            request.app.queue,
            request.app.cache,
            str(log.tid),
        )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"outlier detection task in progress": str(log.tid)},
    )


@router.get("/{dataset_id}/outliers", response_description="Outliers retrieved",
            description="Retrieves outliers detected for a specific dataset."
)
async def get_outliers(
    dataset_id: str,
    request: Request,
    with_data: bool = False,
    skip: int = 0,
    limit: int = 0,
):
    fields = {
        "_id": 0,
        "file": 1,
        "score": 1,
    }
    fields.update({"data": 1}) if with_data else fields
    if outliers := request.app.outlier[dataset_id].find(
        {},
        fields,
    ):
        if skip:
            outliers = outliers.skip(skip)
        if limit:
            outliers = outliers.limit(limit)
        return await outliers.to_list(length=None)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outliers of [{dataset_id}] not found",
        )


@router.delete(
    "/{dataset_id}/outliers",
    response_description="Outliers deleted",
    description="Deletes all detected outliers associated with a specific dataset."

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
    description="Initiates the generation of a report for a specified dataset based on provided options. Optionally triggers the report generation task for processing."
)
async def generate_report(
    dataset_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    trigger: bool = True,
    options: ReportOptions = Body(...),
):
    if not await request.app.scan[dataset_id].find().to_list(length=None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No output data found for dataset [{dataset_id}].",
        )

    found = await ReportLog.find_one(ReportLog.collection == dataset_id)
    metadata = (await TaskLog.find_one({"collection": dataset_id})).options
    metadata.update(
        {
            "length": int(
                (await TaskLog.find_one(TaskLog.collection == dataset_id)).finished
                * options.downsample
            ),
        }
    )
    log = await ReportLog.find_one(ReportLog.collection == dataset_id).upsert(
        Set(
            {
                ReportLog.options.minimal: options.minimal,
                ReportLog.options.downsample: options.downsample,
                ReportLog.file_id: None,
                ReportLog.filename: None,
                ReportLog.metadata: metadata,
            }
        ),
        on_insert=ReportLog(
            collection=dataset_id,
            options=options,
            metadata=metadata,
        ),
        response_type=UpdateResponse.NEW_DOCUMENT,
    )

    if found and found.file_id:
        await remove_report(found.file_id, request.app.log)

    if trigger:
        background_tasks.add_task(
            run_report_tasks,
            request.app.scan,
            request.app.log,
            request.app.queue,
            request.app.cache,
            str(log.tid),
        )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"reporting in progress": str(log.tid)},
    )


@router.get(
    "/{dataset_id}/report",
    response_description="Report retrieved",
    response_class=HTMLResponse,
    description="Retrieves the report generated for a specific dataset."
)
async def get_report(dataset_id: str, request: Request):
    if (
        doc := await request.app.log["reports"].find_one({"collection": dataset_id})
    ) is not None:
        file_id = doc["file_id"]
        try:
            if html_content := await retrieve_report(file_id, request.app.log):
                return HTMLResponse(content=html_content, status_code=200)
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Report of [{dataset_id}] not found",
                )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report of [{dataset_id}] not found: {str(e)}",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report of [{dataset_id}] not found",
        )


@router.delete(
    "/{dataset_id}/report",
    response_description="Dataset report deleted",
    description="Deletes the report generated for a specific dataset."
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


@router.post(
    "/preprocessing",
    response_description="Image preprocessing task added",
    status_code=status.HTTP_202_ACCEPTED,
    description="Initiates a preprocessing task based on provided parameters. Initiates the task asynchronously and returns a task ID for tracking."

)
async def post_preprocessing_task(
    request: Request,
    background_tasks: BackgroundTasks,
    task: PreprocessingLog = Body(...),
):
    log = await task.insert()

    background_tasks.add_task(
        run_preprocessing_tasks,
        request.app.log,
        request.app.queue,
        request.app.cache,
        str(log.tid),
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"Preprocessing task in progress": str(log.tid)},
    )


@router.get(
    "/preprocessing/{task_id}",
    response_description="Image preprocessing task status retrieved",
    status_code=status.HTTP_200_OK,
    description="Fetches details of a preprocessing task based on its task ID."

)
async def get_preprocessing_task(
    task_id: str,
):
    task = await PreprocessingLog.find_one({"tid": task_id})
    data = task.model_dump()
    if task.status == Status.done:
        return data
    else:
        return JSONResponse(
            status_code=status.HTTP_102_PROCESSING,
            content={"Preprocessing task in progress": str(task.tid)},
        )


@router.delete(
    "/preprocessing/{task_id}",
    response_description="Preprocessing task deleted",
    description="Deletes a preprocessing task and its associated output based on its task ID."

)
async def delete_preprocessing(task_id: str):
    try:
        log = await PreprocessingLog.find_one({"tid": task_id})
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preprocessing log of [{task_id}] not found: {str(e)}",
        )
    try:
        shutil.rmtree(log.target)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove preprocessing task output of [{task_id}]: {str(e)}",
        )

    try:
        await log.delete()
        return {"info": f"Preprocessing log of [{task_id}] deleted."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to remove preprocessing log of [{task_id}] not found: {str(e)}",
        )


@router.delete(
    "/preprocessing/{task_id}/log",
    response_description="Preprocessing task log deleted",
    description="Deletes the preprocessing log associated with a specific task ID."

)
async def delete_preprocessing_log(task_id: str, request: Request):
    result = await request.app.log["preprocessings"].delete_many({"tid": task_id})
    if result.deleted_count > 0:
        return {
            "info": f"Preprocessing log of [{task_id}] deleted: {result.deleted_count}"
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preprocessing log of [{task_id}] not found",
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


@router.get("/status", response_description="Scan task status retrieved",description="Fetches the status of tasks currently in progress or queued for processing."
)
async def get_task_status(request: Request):
    log = request.app.log
    tasks = await log["tasks"].find({"status": {"$lt": 2}}).to_list(length=None)
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


@router.post(
    "/pause",
    response_description="Task queue paused",
    description="Pauses and clears all tasks from the task queue.",
)
async def pause_queue(request: Request):
    ray.shutdown()

    queue = request.app.queue
    cache = request.app.cache

    while await queue.llen("task_queue") > 0:
        tid = await queue.rpop("task_queue")
        await queue.delete(tid)
    await queue.delete("task_queue")

    # cancelled = 0
    # for task in await cache.lrange("task_refs", 0, -1):
    #     try:
    #         ray.cancel(pickle.loads(task))
    #         cancelled += 1
    #     except TypeError as e:
    #         # print(f"Task not found: {str(e)}")
    #         pass
    #     except Exception as e:
    #         print(f"Failed to cancel ray task: {str(e)}")
    await cache.ltrim("task_refs", 1, 0)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": "Successful, task queue paused."},
    )


@router.post(
    "/pause/{task_id}",
    response_description="Task paused",
    description="Pauses a specific task identified by its task ID from the task queue.",
)
async def pause_task(
    task_id: str,
    request: Request,
):
    queue = request.app.queue
    cache = request.app.cache

    ray.shutdown()
    await cache.ltrim("task_refs", 1, 0)

    task_list = []
    while await queue.llen("task_queue") > 0:
        tid = await queue.rpop("task_queue")
        if tid == task_id:
            await queue.delete(tid)
        else:
            task_list.append(tid)

    [await queue.lpush("task_queue", tid) for tid in task_list]

    if not (log := await TaskLog.find_one(TaskLog.tid == task_id)):
        raise HTTPException(status_code=404, detail="Task not found!")

    log.status = Status.new
    await log.save()

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": f"Successful, task [{task_id}] paused."},
    )


@router.post("/resume", response_description="Task queue resumed",description="Resumes processing tasks in the task queue if there are pending tasks."
)
async def resume_queue(request: Request, background_tasks: BackgroundTasks):
    if (
        len(
            await request.app.log["tasks"]
            .find({"status": {"$lt": 2}})
            .to_list(length=None)
        )
        > 0
    ):
        background_tasks.add_task(
            run_scan_tasks,
            request.app.scan,
            request.app.log,
            request.app.queue,
            request.app.cache,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"message": "Successful, task queue resumed."},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task queue is empty"
        )


@router.post("/resume/{task_id}", response_description="Task resumed",description="Resumes processing of a specific task identified by its task ID, if it is found in the task queue."
)
async def resume_task(
    task_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    if (
        len(
            await request.app.log["tasks"]
            .find(
                {
                    "status": {"$lt": 2},
                    "tid": task_id,
                },
            )
            .to_list(length=None)
        )
        > 0
    ):
        background_tasks.add_task(
            run_scan_tasks,
            request.app.scan,
            request.app.log,
            request.app.queue,
            request.app.cache,
            task_id,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"message": f"Successful, task [{task_id}] resumed."},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task [{task_id}] not found."
        )


@router.post("/clear", response_description="Task queue stopped and cleared",description="Clears all tasks from the task queue and removes corresponding task logs from the database."
)
async def clear_task_queue(request: Request):
    queue = request.app.queue
    log = request.app.log
    while await queue.llen("task_queue") > 0:
        tid = await queue.rpop("task_queue")
        await queue.delete(tid)
        await log["tasks"].delete_one({"tid": tid})
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content="Task queue cleared",
    )


# @router.get("/info", response_description="BQAT backend info retrieved",description="Fetches version information."
# )
# async def get_version_info():
#     return JSONResponse(status_code=status.HTTP_200_OK, content=get_info())


@router.post(
    "/report/remote",
    response_description="Report generation task added",
    status_code=status.HTTP_202_ACCEPTED,
    description="Uploads a file, initiates a report generation task, and optionally triggers its execution."

)
async def generate_remote_report(
    file: UploadFile,
    request: Request,
    background_tasks: BackgroundTasks,
    trigger: bool = True,
    minimal: bool = False,
    downsample: float = 1,
):
    if not os.path.exists(Settings().TEMP):
        os.mkdir(Settings().TEMP)

    file_path = f"{Settings().TEMP}{uuid.uuid4()}_{file.filename}"
    with open(file_path, "wb") as out:
        if not (data := await file.read()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No output data in [{file.filename}].",
            )
        out.write(data)

    task = await ReportLog(
        external_input=file_path,
        options=ReportOptions(minimal=minimal, downsample=downsample),
    ).insert()

    if trigger:
        background_tasks.add_task(
            run_report_tasks,
            request.app.scan,
            request.app.log,
            request.app.queue,
            request.app.cache,
            str(task.tid),
        )

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"reporting in progress": str(task.tid)},
        )
    else:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"reporting task added": str(task.tid)},
        )
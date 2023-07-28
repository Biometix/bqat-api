import glob
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime

import pandas as pd
import ray
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from pandas_profiling import ProfileReport
from pyod.models.cblof import CBLOF
from pyod.models.copod import COPOD
from pyod.models.ecod import ECOD
from pyod.models.iforest import IForest
from pyod.models.knn import KNN
from pyod.models.pca import PCA
from redis.asyncio.client import Redis
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn

from api.config import Settings
from api.config.models import CollectionLog, Status, TaskQueue
from bqat.bqat_core import __name__, __version__, scan

DETECTORS = ("ECOD", "CBLOF", "IForest", "KNN", "COPOD", "PCA")


@ray.remote
def scan_task(path, options):
    try:
        result = scan(path, **options)
        result.update({"tag": get_tag(result["file"])})
    except Exception as e:
        print(f">>>> File scan error: {str(e)}")
        log = {"file": path, "error": str(e)}
        return log
    return result


@ray.remote
def report_task(data, options):
    try:
        report = generate_report(data, **options)
    except Exception as e:
        print(f">>>> Report generation failed: {str(e)}")
        log = {"options": options, "error": str(e)}
        return log
    return report


@ray.remote
def outlier_detection_task(data, options):
    try:
        outliers = get_outliers(data, **options)
    except Exception as e:
        print(f">>>> Outlier detection failed: {str(e)}")
        log = {"options": options, "error": str(e)}
        return log
    return outliers


async def run_scan_tasks(
    scan: AsyncIOMotorDatabase, log: AsyncIOMotorDatabase, queue: Redis
) -> None:
    tasks = await log["tasks"].find({"status": {"$lt": 2}}).to_list(length=None)
    for task in tasks:
        tid = str(task.get("tid"))
        await queue.lpush("task_queue", tid)
        if not await queue.exists(tid):
            await queue.set(tid, json.dumps(TaskQueue(total=task.get("input")).dict()))

    task_timer = time.time()
    file_count = 0
    tasks = []

    while await queue.llen("task_queue") > 0:
        tid = (await queue.lrange("task_queue", -1, -1))[0]
        task = await log["tasks"].find_one({"tid": tid})
        options = task.get("options")
        collection = task.get("collection")
        pending = [
            sample["path"]
            for sample in await log["samples"]
            .find({"tid": tid, "status": 0})
            .to_list(length=None)
        ]

        if task.get("status") == Status.new:
            if not await log["datasets"].find_one({"collection": collection}):
                await CollectionLog(collection=collection, options=options).create()

        task = await log["tasks"].find_one_and_update(
            {"tid": tid}, {"$set": {"status": 1}}
        )
        with Progress(
            SpinnerColumn(), MofNCompleteColumn(), *Progress.get_default_columns()
        ) as p:
            task_progress = p.add_task("[cyan]Sending task...", total=len(pending))
            for file in pending:
                tasks.append(scan_task.remote(file, options))
                file_count += 1
                p.update(task_progress, advance=1)
                if p.finished:
                    break

        step = 100
        counter = 0
        with Progress(
            SpinnerColumn(), MofNCompleteColumn(), *Progress.get_default_columns()
        ) as p:
            task_progress = p.add_task("[cyan]Scanning...", total=len(pending))
            while not p.finished:
                scan_timer = time.time()
                if len(tasks) < step:
                    ready = tasks
                    results = ray.get(tasks)
                    not_ready = []
                else:
                    ready, not_ready = ray.wait(tasks, num_returns=step, timeout=3)
                    results = ray.get(ready)
                if not results:
                    break
                counter += len(ready)
                await scan[collection].insert_many(results)
                files = [entry["file"] for entry in results]
                scan_timer = time.time() - scan_timer
                p.update(task_progress, advance=len(files))
                task = await log["tasks"].find_one_and_update(
                    {"tid": tid},
                    {"$inc": {"elapse": scan_timer, "finished": len(files)}},
                )
                await log["datasets"].find_one_and_update(
                    {"collection": collection},
                    {
                        # "$set": {"modified": datetime.now()},
                        "$currentDate": {"modified": True},
                        "$inc": {"samples": len(files)},
                    },
                )
                # for file in files:
                #     await log["samples"].find_one_and_update(
                #         {
                #             "tid": tid,
                #             "path": file
                #         },
                #         {
                #             "$set": { "status": 2 }
                #         }
                #     )
                elapse = task.get("elapse") + scan_timer
                status = json.loads(await queue.get(tid))
                status["done"] += len(files)
                throughput = status["done"] / elapse
                eta = (status["total"] - status["done"]) / throughput
                status["eta"] = eta
                t_min, t_sec = divmod(eta, 60)
                t_hr, t_min = divmod(t_min, 60)
                print(f">> Finished: {counter}")
                print(f">> ETA: {int(t_hr)}h{int(t_min)}m{int(t_sec)}s")
                print(f">> Throughput: {throughput:.2f} items/s\n")
                await queue.set(tid, json.dumps(status))
                tasks = not_ready

        task = await log["tasks"].find_one({"tid": tid})
        if task and (task.get("input") <= task.get("finished")):
            await log["tasks"].find_one_and_update(
                {"tid": tid}, {"$set": {"status": 2}}
            )
            await queue.rpop("task_queue")
            await queue.delete(tid)
            await log["samples"].delete_many({"tid": tid})

    if os.path.exists(Settings().TEMP):
        shutil.rmtree(Settings().TEMP)

    task_timer = time.time() - task_timer
    t_min, t_sec = divmod(task_timer, 60)
    t_hr, t_min = divmod(t_min, 60)
    print(f">> File count: {file_count}")
    print(f">> Throughput: {(file_count/task_timer):.2f} items/s")
    print(f">> Process time: {int(t_hr)}h{int(t_min)}m{int(t_sec)}s")
    print(f">> Collection: {collection}")
    print(">>> Finished <<<")


async def run_report_tasks(
    scan: AsyncIOMotorDatabase, log: AsyncIOMotorDatabase
) -> None:
    tasks = []
    for task in await log["reports"].find().to_list(length=None):
        if not task.get("file_id"):
            tasks.append(task)

    for task in tasks:
        task_timer = time.time()
        data = []
        dataset_id = task.get("collection")
        print(f">> Generate report: {dataset_id}")
        for doc in await scan[dataset_id].find().to_list(length=None):
            doc.pop("_id")
            data.append(doc)
        options = {"minimal": task.get("minimal"), "downsample": task.get("downsample")}
        report = report_task.remote(data, options)
        html_content = ray.get(report)
        fs = AsyncIOMotorGridFSBucket(log)
        file_id = await fs.upload_from_stream(
            f"report_{dataset_id}",
            html_content.encode(),
            metadata={"contentType": "text/plain"},
        )
        filename = (
            f"report_{dataset_id}_minimal"
            if task.get("minimal")
            else f"report_{dataset_id}"
        )
        await log["reports"].find_one_and_update(
            {"_id": task["_id"]}, {"$set": {"file_id": file_id, "filename": filename}}
        )
        task_timer = time.time() - task_timer
        t_min, t_sec = divmod(task_timer, 60)
        t_hr, t_min = divmod(t_min, 60)
        print(f">> Process time: {int(t_hr)}h{int(t_min)}m{int(t_sec)}s")
    print(">>> Finished <<<")


async def run_outlier_detection_tasks(
    dataset_id: str,
    options: dict,
    scan: AsyncIOMotorDatabase,
    log: AsyncIOMotorDatabase,
) -> None:
    task_timer = time.time()
    data = []
    file = []
    for doc in (
        await scan[dataset_id].find().to_list(length=None)
    ):  # TODO instead of reconstruct a dict list, make the query with required attributes
        sample = {k: float(doc.get(k, 0)) for k in options["columns"]}
        data.append(sample)
        file.append(doc.get("file"))

    task = outlier_detection_task.remote(data, {"detector": options.get("detector")})
    label, score = ray.get(task)
    outliers = pd.DataFrame(
        list(zip(file, label, score)), columns=["file", "label", "score"]
    )
    outliers = outliers[outliers["label"] == 1].drop(["label"], axis=1)
    outliers["collection"] = dataset_id
    await log["outliers"].insert_many(outliers.to_dict("records"))

    task_timer = time.time() - task_timer
    t_min, t_sec = divmod(task_timer, 60)
    t_hr, t_min = divmod(t_min, 60)
    print(f">> Process time: {int(t_hr)}h{int(t_min)}m{int(t_sec)}s")
    print(">>> Finished <<<")


async def run_test_tasks() -> str:
    out = subprocess.run(
        ["python3.8", "-m", "pytest", "tests", "-v"], capture_output=True
    )
    return out.stdout


def get_files(folder, ext=("jpg", "jpeg", "png", "bmp", "wsq", "jp2", "wav")) -> list:
    file_globs = []
    files = []
    for ext in extended(ext):
        file_globs.append(glob.iglob(folder + "**/*." + ext, recursive=True))
    for file_glob in file_globs:
        for file in file_glob:
            files.append(file)
    return files


def extended(ext_list):
    """Extends lower case file extensions list with UPPER and Capitalize ones."""
    full_list = []
    for ext in ext_list:
        full_list.extend([ext.upper(), ext.capitalize()])
    full_list.extend(ext_list)
    return full_list


def edit_attributes(doc, edit) -> dict:
    attr = {}
    if "yaw" or "pitch" or "roll" in edit.keys():
        pose = doc.get("pose")
        if yaw := edit.get("yaw"):
            pose["yaw"] = yaw
        if pitch := edit.get("pitch"):
            pose["pitch"] = pitch
        if roll := edit.get("roll"):
            pose["roll"] = roll
        attr.update({"pose": pose})
    if "age" or "gender" or "race" or "emotion" in edit.keys():
        face = doc.get("face")
        if age := edit.get("age"):
            face["age"] = age
        if gender := edit.get("gender"):
            face["gender"] = gender
        if emotion := edit.get("emotion"):
            face["dominant_emotion"] = emotion
        if race := edit.get("race"):
            face["dominant_race"] = race
        attr.update({"face": face})
    if quality := edit.get("quality"):
        attr.update({"quality": quality})
    return attr


def get_md5(filepath):
    md5_hash = hashlib.md5()
    with open(filepath, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
    return md5_hash.hexdigest()


def check_options(options, modality):
    if not options.get("mode"):
        options["mode"] = modality
    if not options.get("engine"):
        options["engine"] = "default"
    if modality == "face":
        if options["engine"] == "default" and not options.get("confidence"):
            options["confidence"] = 0.7
        elif options["engine"] == "biqt":
            pass
    elif modality == "fingerprint":
        if not options.get("source") or options.get("source") == "default":
            options["source"] = ["jpg", "jpeg", "bmp", "jp2", "wsq"]
        if not options.get("target") or options.get("target") == "default":
            options["target"] = "png"
    elif modality == "iris":
        pass
    elif modality == "speech":
        if not options.get("type"):
            options.update({"type": "file"})
        if options.get("type") == "folder":
            options.update({"type": "file"})
            print("folder scan not supported")
    else:
        return False
    return options


def generate_report(data, **options):
    temp = "report.html"
    df = pd.DataFrame.from_dict(data)
    # df.set_index("file", inplace=True)
    # df = df.drop(columns=['file'])
    if options.get("downsample"):
        df = df.sample(frac=options.get("downsample", 0.05))
    ProfileReport(
        df,
        title=f"Biometric Quality Report by BQAT {__version__}",
        explorative=True,
        minimal=options.get("minimal", False),
        correlations={"cramers": {"calculate": False}},
        html={"navbar_show": True, "style": {"theme": "united"}},
    ).to_file(temp)

    with open(temp, "r") as f:
        html = f.read()
    os.remove(temp)

    return html


async def retrieve_report(file_id, db):
    fs = AsyncIOMotorGridFSBucket(db)
    file = open("myfile", "wb+")
    await fs.download_to_stream(file_id, file)
    file.seek(0)
    return file.read()


async def remove_report(file_id, db):
    fs = AsyncIOMotorGridFSBucket(db)
    await fs.delete(file_id)


def get_info():
    return {"backend": __name__, "version": __version__}


def get_tag(identifier):
    tag = hashlib.sha1()
    tag.update(identifier.encode())
    return tag.hexdigest()


def get_outliers(data: list, detector: str = "ECOD"):
    # HACK
    # _, ver, _ = platform.python_version_tuple()
    # if ver >= 10:
    #     match detector:
    #         case "ECOD":
    #             clf = ECOD()
    #             # clf = ECOD(n_jobs=8)
    #         case "DeepSVDD":
    #             clf = DeepSVDD()
    #         case "CBLOF":
    #             clf = CBLOF()
    #         case "IForest":
    #             clf = IForest()
    #         case "KNN":
    #             clf = KNN()
    #         case "COPOD":
    #             clf = COPOD()
    #         case "PCA":
    #             clf = PCA()
    #         case _:
    #             print(f"detector: {detector} not recognized, fallback to ECOD.")
    #             clf = ECOD()
    # else:
    #     if detector in DETECTORS:
    #         clf = eval(detector)
    #     else:
    #         print(f"detector: {detector} not recognized, fallback to ECOD.")
    #         clf = ECOD()
    if detector in DETECTORS:
        clf = eval(detector)
    else:
        print(f"detector [{detector}] not recognized, fallback to ECOD.")
        clf = ECOD()

    clf.fit(pd.DataFrame.from_records(data))
    labels = clf.labels_
    scores = clf.decision_scores_
    return labels, scores

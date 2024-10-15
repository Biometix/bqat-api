import asyncio
import csv
import glob
import hashlib
import json
import os
import pickle
import re
import shutil
import subprocess
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import ray

# import wsq # Somehow it needs to be imported with in ray function
from beanie import PydanticObjectId

# from bson.binary import Binary
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from pandas_profiling import ProfileReport
from PIL import Image, ImageOps
from pymongo import UpdateOne
from pyod.models.cblof import CBLOF
from pyod.models.copod import COPOD

# from pyod.models.deep_svdd import DeepSVDD
# from pyod.models.dif import DIF
from pyod.models.ecod import ECOD
from pyod.models.iforest import IForest
from pyod.models.knn import KNN
from pyod.models.pca import PCA
from redis.asyncio.client import Redis
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn

from api.config import Settings
from api.config.models import (
    CollectionLog,
    FaceSpecBIQT,
    FaceSpecBQAT,
    FaceSpecOFIQ,
    FingerprintSpecDefault,
    IrisSpecDefault,
    # DetectorOptions,
    # ReportLog,
    SpeechSpecDefault,
    Status,
    TaskQueue,
)
from bqat.bqat_core import __name__, __version__
from bqat.bqat_core import scan as process


@ray.remote(num_cpus=Settings().CPU_RESERVE_PER_TASK)
def scan_task(path, options):
    try:
        if options.get("engine") == "ofiq" and options.get("type") == "folder":
            print(f">>>> Scanning folder {path}")
            return process(path, **options)
        else:
            result = process(path, **options)
            # result.update({"tag": get_tag(result.get("file", path))})
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


@ray.remote
def preprocess_task(file: str, output: dir, config: dict) -> None:
    try:
        import wsq
        file = Path(file)
        pattern = config.get("pattern", None)
        
        if pattern and not file.match(f"*{pattern}{file.suffix}"):
            print(f">>>> File {file} does not match pattern {pattern}{file.suffix}")
            return
        else:
            print(f">>>> Preprocessing {file}")
        if not Path(output).exists():
            Path(output).mkdir(parents=True, exist_ok=True)
        with Image.open(file) as img:
            match config.get("mode", "rgb"):
                case "rgb":
                    img = img.convert("RGB")
                case "rgba":
                    img = img.convert("RGBA")
                case "grayscale" | "greyscale":
                    img = ImageOps.grayscale(img)
                    # img = img.convert("L")
                case "hsv":
                    img = img.convert("HSV")
                case "cmyk":
                    img = img.convert("CMYK")
                case "ycbcr":
                    img = img.convert("YCbCr")
                case "bw":
                    img = img.convert("1")
                case _:
                    img = img.convert("RGB")

            if width := config.get("width", False):
                height = int(width * img.height / img.width)
                img = img.resize((width, height))
            if frac := config.get("frac", False):
                img = img.resize((int(img.width * frac), int(img.height * frac)))

            if target := config.get("target", False):
                processed = Path(output) / file.parent.relative_to(Settings().DATA) / f"{file.stem}.{target}"
            else:
                processed = Path(output) / file.parent.relative_to(Settings().DATA) / file.name
            if not processed.parent.exists():
                processed.parent.mkdir(parents=True, exist_ok=True)
            if target=='wsq':
                img = ImageOps.grayscale(img)
            img.save(processed)
    except Exception as e:
        print(f">>>> Preprocess task error: {str(e)}")


async def run_scan_tasks(
    scan: AsyncIOMotorDatabase,
    log: AsyncIOMotorDatabase,
    queue: Redis,
    cache: Redis,
    task_id: str | None = None,
) -> None:
    if task_id:
        tasks = await log["tasks"].find({"tid": task_id}).to_list(length=None)
    else:
        tasks = await log["tasks"].find({"status": {"$lt": 2}}).to_list(length=None)

    for task in tasks:
        tid = str(task.get("tid"))
        await queue.lpush("task_queue", tid)
        if not await queue.exists(tid):
            await queue.set(
                tid,
                TaskQueue(
                    total=task.get("total", 0), done=task.get("finished", 0)
                ).model_dump_json(),
            )

    try:
        while await queue.llen("task_queue") > 0:
            task_timer = time.time()
            file_count = 0
            tasks = []

            tid = (await queue.lrange("task_queue", -1, -1))[0]
            if not tid:
                continue

            task = await log["tasks"].find_one({"tid": tid})
            options = task.get("options")
            collection = task.get("collection")

            if task.get("status") == Status.new:
                if not await log["datasets"].find_one({"collection": collection}):
                    await CollectionLog(collection=collection, options=options).create()

            # Split folder scan
            if options.get("engine") == "ofiq" and options.get("type") != "folder":
                pending = [
                    sample["path"]
                    for sample in await log["samples"]
                    .find({"tid": tid, "status": 0})
                    .to_list(length=None)
                ]
                options["type"] = "folder"

                task = await log["tasks"].find_one_and_update(
                    {"tid": tid}, {"$set": {"status": 1}}
                )

                with Progress(
                    SpinnerColumn(),
                    MofNCompleteColumn(),
                    *Progress.get_default_columns(),
                ) as p:
                    task_progress = p.add_task(
                        "[cyan]Executing task...", total=task.get("total", 0)
                    )
                    batch_no = 0
                    batch_start = time.time()
                    for folder in pending:
                        batch_no += 1
                        batch_task = [scan_task.remote(folder, options)]

                        await log["tasks"].find_one_and_update(
                            {"tid": tid},
                            {
                                "$set": {
                                    "status": 1,
                                }
                            },
                        )
                        await cache.rpush("task_refs", *[pickle.dumps(batch_task[0])])

                        batch = len(get_files(folder))
                        print(
                            f">> Batch {batch_no}/{len(pending)}, size: {batch}/{task.get('total')}"
                        )
                        try:
                            ready, not_ready = ray.wait(batch_task, timeout=1)
                            while not_ready:
                                await asyncio.sleep(3)
                                ready, not_ready = ray.wait(not_ready, timeout=0.1)
                                print(
                                    f">> Processing batch {batch_no}, elapse: {time.time() - batch_start:.2f}/{time.time() - task_timer:.2f}..."
                                )
                            outputs = ray.get(batch_task)
                            await log["tasks"].find_one_and_update(
                                {"tid": tid},
                                {
                                    "$set": {
                                        "status": 2,
                                    }
                                },
                            )
                            await cache.ltrim("task_refs", 1, 0)
                        except (ray.exceptions.TaskCancelledError, ValueError):
                            print(f"Task was cancelled: {tid}")
                            await log["tasks"].find_one_and_update(
                                {"tid": task["tid"]},
                                {
                                    "$set": {
                                        "status": 0,
                                    },
                                },
                            )
                            await cache.ltrim("task_refs", 1, 0)
                            await queue.delete(tid)
                            return
                        batch_count = 0
                        for output in outputs:
                            result_list = output.get("results", [])
                            for result in result_list:
                                file_count += 1
                                batch_count += 1
                                await scan[collection].insert_one(result)
                        await log["samples"].find_one_and_update(
                            {"tid": tid, "path": folder},
                            {
                                "$set": {
                                    "status": 2,
                                    "modified": datetime.now(),
                                }
                            },
                        )
                        await cache.ltrim("task_refs", 1, 0)
                        p.update(task_progress, advance=batch_count)
                        batch_timer = time.time() - batch_start
                        task = await log["tasks"].find_one_and_update(
                            {"tid": tid},
                            {
                                "$inc": {
                                    "elapse": int(batch_timer),
                                    "finished": batch_count,
                                },
                                # "$set": {
                                #     "elapse": time.time() - task_timer,
                                # },
                            },
                        )
                        await log["datasets"].find_one_and_update(
                            {"collection": collection},
                            {
                                # "$set": {"modified": datetime.now()},
                                "$currentDate": {"modified": True},
                                "$inc": {"samples": batch_count},
                            },
                        )
                        elapse = (
                            task["elapse"]
                            if task["elapse"] > 0
                            else batch_timer
                            if batch_timer > 0
                            else 1
                        )
                        status = json.loads(await queue.get(tid))
                        status["done"] += batch_count
                        throughput = status["done"] / elapse
                        throughput = 1 if not throughput else throughput
                        eta = (status["total"] - status["done"]) / throughput
                        status["eta"] = int(eta)
                        print(f">> Finished: {status['done']}/{task.get('total', 1)}")
                        print(f">> Elapsed: {convert_sec_to_hms(int(elapse))}")
                        print(f">> ETA: {convert_sec_to_hms(int(eta))}")
                        print(f">> Throughput: {throughput:.2f} items/s\n")
                        await queue.set(tid, json.dumps(status))

                        shutil.rmtree(folder)

                        if p.finished:
                            break
                        batch_start = time.time()

                await log["tasks"].find_one_and_update(
                    {"tid": tid},
                    {
                        "$set": {
                            "status": 2,
                            "modified": datetime.now(),
                        }
                    },
                )
                await cache.ltrim("task_refs", 1, 0)
                await queue.rpop("task_queue")
                await queue.delete(tid)
                await log["samples"].delete_many({"tid": tid})

            # Whole folder scan
            elif options.get("mode") == "speech" or options.get("type") == "folder":
                input_folder = (
                    await log["samples"].find_one({"tid": tid, "status": 0})
                )["path"]
                file_total = task.get("total")

                if options.get("mode") == "speech":
                    dir_list = [
                        str(i) + "/"
                        for i in Path(input_folder).rglob("*")
                        if (i.is_dir() and len(list(i.glob("*.[Ww][Aa][Vv]"))) > 0)
                    ]
                    if len(list(Path(input_folder).glob("*.[Ww][Aa][Vv]"))) > 0:
                        dir_list.append(input_folder)

                elif options.get("type") == "folder":
                    accepted_types = ["jpg", "jpeg", "png", "bmp", "wsq", "jp2"]

                    dir_list = [
                        str(i) + "/"
                        for i in Path(input_folder).rglob("*")
                        if i.is_dir()
                        and any(list(i.glob(f"*.{ext}")) for ext in accepted_types)
                    ]

                    if any(
                        list(Path(input_folder).glob(f"*.{ext}"))
                        for ext in accepted_types
                    ):
                        dir_list.append(input_folder)

                else:
                    dir_list = [
                        str(i) for i in Path(input_folder).rglob("*") if i.is_dir()
                    ]
                    dir_list.append(input_folder)

                for input_folder in dir_list:
                    subtasks = []
                    file_total = len(list(Path(input_folder).glob("*.*")))
                    with Progress(
                        SpinnerColumn(),
                        MofNCompleteColumn(),
                        *Progress.get_default_columns(),
                    ) as p:
                        task_progress = p.add_task(
                            "[purple]Sending...", total=file_total
                        )
                        subtasks.append(
                            scan_task.remote(
                                input_folder,
                                options,
                            )
                        )
                        await log["tasks"].find_one_and_update(
                            {"tid": tid},
                            {
                                "$set": {
                                    "status": 1,
                                }
                            },
                        )
                        await cache.rpush(
                            "task_refs",
                            *[pickle.dumps(task) for task in subtasks],
                        )

                        p.update(task_progress, completed=file_total)

                    with Progress(
                        SpinnerColumn(),
                        MofNCompleteColumn(),
                        *Progress.get_default_columns(),
                    ) as p:
                        task_progress = p.add_task(
                            "[purple]Finalising...", total=file_total
                        )
                        try:
                            ready, not_ready = ray.wait(subtasks, timeout=3)
                            while not_ready:
                                await asyncio.sleep(10)
                                ready, not_ready = ray.wait(not_ready, timeout=3)
                                print(f"{datetime.now()}: processing...")
                            outputs = ray.get(subtasks)
                        except (ray.exceptions.TaskCancelledError, ValueError):
                            print(f"Task was cancelled: {tid}")
                            await log["tasks"].find_one_and_update(
                                {"tid": task["tid"]},
                                {
                                    "$set": {
                                        "status": 0,
                                    },
                                },
                            )
                            await cache.ltrim("task_refs", 1, 0)
                            await queue.delete(tid)
                            return
                        for output in outputs:
                            result_list = output.get("results", [])
                            for result in result_list:
                                file_count += 1
                                await scan[collection].insert_one(result)
                                p.update(task_progress, advance=1)
                                if p.finished:
                                    break

                        p.update(task_progress, completed=file_total)

                scan_timer = time.time() - task_timer
                task = await log["tasks"].find_one_and_update(
                    {"tid": tid},
                    {"$inc": {"elapse": scan_timer, "finished": file_count}},
                )
                await log["datasets"].find_one_and_update(
                    {"collection": collection},
                    {
                        # "$set": {"modified": datetime.now()},
                        "$currentDate": {"modified": True},
                        "$inc": {"samples": file_count},
                    },
                )

                await log["tasks"].find_one_and_update(
                    {"tid": tid},
                    {
                        "$set": {
                            "status": 2,
                            "modified": datetime.now(),
                        }
                    },
                )
                await cache.ltrim("task_refs", 1, 0)
                await queue.rpop("task_queue")
                await queue.delete(tid)
                await log["samples"].delete_many({"tid": tid})

            # Individual file scan
            else:
                pending = [
                    sample["path"]
                    for sample in await log["samples"]
                    .find({"tid": tid, "status": 0})
                    .to_list(length=None)
                ]

                task = await log["tasks"].find_one_and_update(
                    {"tid": tid}, {"$set": {"status": 1}}
                )
                with Progress(
                    SpinnerColumn(),
                    MofNCompleteColumn(),
                    *Progress.get_default_columns(),
                ) as p:
                    task_progress = p.add_task(
                        "[cyan]Sending task...", total=len(pending)
                    )
                    for file in pending:
                        tasks.append(scan_task.remote(file, options))
                        file_count += 1
                        p.update(task_progress, advance=1)
                        if p.finished:
                            break

                await log["tasks"].find_one_and_update(
                    {"tid": tid},
                    {
                        "$set": {
                            "status": 1,
                        }
                    },
                )
                await cache.rpush("task_refs", *[pickle.dumps(task) for task in tasks])

                step = Settings().TASK_WAIT_INTERVAL_STEP
                counter = 0
                gear = 1
                with Progress(
                    SpinnerColumn(),
                    MofNCompleteColumn(),
                    *Progress.get_default_columns(),
                ) as p:
                    task_progress = p.add_task("[cyan]Scanning...", total=len(pending))
                    scan_timer = time.time()
                    while not p.finished:
                        await asyncio.sleep(Settings().TASK_WAIT_INTERVAL_SLEEP)
                        try:
                            if len(tasks) < step:
                                ready = tasks
                                results = ray.get(tasks)
                                not_ready = []
                            else:
                                ready, not_ready = ray.wait(
                                    tasks,
                                    num_returns=step,
                                    timeout=Settings().TASK_WAIT_INTERVAL_TIMEOUT,
                                )
                                while not ready and not_ready:
                                    ready, not_ready = ray.wait(
                                        tasks,
                                        num_returns=step,
                                        timeout=Settings().TASK_WAIT_INTERVAL_TIMEOUT,
                                    )
                                    step -= int(0.2 * step)
                                results = ray.get(ready)
                                if len(results) < step:
                                    step = len(results)
                                    gear = 1
                                else:
                                    step += int(0.5 * gear * step)
                                    gear += 1
                                if step < 1:
                                    step = 1
                                    gear = 1
                        except (ray.exceptions.TaskCancelledError, ValueError):
                            print(f"Task was cancelled: {tid}")
                            await log["tasks"].find_one_and_update(
                                {"tid": task["tid"]},
                                {
                                    "$set": {
                                        "status": 0,
                                    },
                                },
                            )
                            await cache.ltrim("task_refs", 1, 0)
                            await queue.delete(tid)
                            return
                        if not results:
                            break
                        counter += len(ready)

                        await scan[collection].insert_many(results)
                        files = [
                            entry.get("file") for entry in results if "file" in entry
                        ]

                        await log["samples"].bulk_write(
                            [
                                UpdateOne(
                                    {"tid": tid, "path": file},
                                    {
                                        "$set": {
                                            "status": 2,
                                        }
                                    },
                                )
                                for file in files
                            ]
                        )

                        scan_timer = time.time() - scan_timer
                        p.update(task_progress, advance=len(files))
                        task = await log["tasks"].find_one_and_update(
                            {"tid": tid},
                            {
                                "$inc": {
                                    "elapse": int(scan_timer),
                                    "finished": len(files),
                                },
                                # "$set": {
                                #     "elapse": time.time() - task_timer,
                                # },
                            },
                        )
                        await log["datasets"].find_one_and_update(
                            {"collection": collection},
                            {
                                # "$set": {"modified": datetime.now()},
                                "$currentDate": {"modified": True},
                                "$inc": {"samples": len(files)},
                            },
                        )

                        elapse = task["elapse"] if task.get("elapse") else 1
                        status = json.loads(await queue.get(tid))
                        status["done"] += len(files)
                        throughput = status["done"] / elapse
                        eta = (status["total"] - status["done"]) / throughput
                        status["eta"] = int(eta)
                        print(f">> Finished: {status["done"]}/{status.get('total', 1)}")
                        print(f">> Elapsed: {convert_sec_to_hms(int(elapse))}")
                        print(f">> ETA: {convert_sec_to_hms(int(eta))}")
                        print(f">> Throughput: {throughput:.2f} items/s\n")
                        await queue.set(tid, json.dumps(status))
                        tasks = not_ready
                        scan_timer = time.time()

                task = await log["tasks"].find_one({"tid": tid})
                if task and (task.get("total", 0) <= task.get("finished")):
                    pass
                else:
                    await asyncio.sleep(3)

                await log["tasks"].find_one_and_update(
                    {"tid": tid},
                    {
                        "$set": {
                            "status": 2,
                            "modified": datetime.now(),
                        }
                    },
                )
                await cache.ltrim("task_refs", 1, 0)
                await queue.rpop("task_queue")
                await queue.delete(tid)
                await log["samples"].delete_many({"tid": tid})
            if options.get("temp"):
                shutil.rmtree(task.get("input"))

            task_timer = time.time() - task_timer
            print(f">> File count: {file_count}")
            print(f">> Throughput: {(file_count/task_timer):.2f} items/s")
            print(f">> Process time: {convert_sec_to_hms(int(task_timer))}")
            print(f">> Output: {collection}")
    except Exception as e:
        print(f"> Task ended:\n---\n{traceback.print_exception(e)}\n---")

    temp_folder = Path(Settings().TEMP) / f"{tid}"
    if temp_folder.exists():
        shutil.rmtree(temp_folder)
        # print("> Temporary folder removed.")
    print(">>> Finished <<<\n")


async def run_report_tasks(
    scan: AsyncIOMotorDatabase,
    log: AsyncIOMotorDatabase,
    queue: Redis,
    cache: Redis,
    task_id: str | None = None,
) -> None:
    tasks = []
    if not task_id:
        for task in await log["reports"].find().to_list(length=None):
            if not task.get("file_id"):
                tasks.append(task)
    else:
        tasks.append(await log["reports"].find_one({"tid": task_id}))

    for task in tasks:
        tid = str(task.get("tid"))
        await queue.lpush("task_queue", tid)

    for task in tasks:
        task_timer = time.time()
        data = []

        if isinstance(task.get("external_input"), str):
            external = True
            with open(task.get("external_input"), newline="") as f:
                reader = csv.DictReader(f, delimiter=",")
                data = list(reader)
            dataset_id = task_id
        else:
            external = False
            dataset_id = task.get("collection")
            for doc in await scan[dataset_id].find().to_list(length=None):
                doc.pop("_id")
                data.append(doc)

        if not data:
            print(f">> No data found, skip generating report: {dataset_id}")
            await log["reports"].find_one_and_update(
                {"tid": task["tid"]},
                {
                    "$set": {
                        "status": 2,
                    },
                },
            )
            continue

        print(f">> Generate report: {dataset_id}")

        options = task.get("options")
        options.update({"collection": dataset_id})
        if not external:
            dataset_log = await log["datasets"].find_one({"collection": dataset_id})
            options.update(
                {
                    "mode": dataset_log["options"].get("mode"),
                    "engine": dataset_log["options"].get("engine"),
                }
            )

        report = [report_task.remote(data, options)]
        await log["reports"].find_one_and_update(
            {"tid": task["tid"]},
            {
                "$set": {
                    "status": 1,
                },
            },
        )
        await cache.rpush("task_refs", *[pickle.dumps(task) for task in report])
        try:
            ready, not_ready = ray.wait(report, timeout=3)
            while not_ready:
                await asyncio.sleep(10)
                ready, not_ready = ray.wait(not_ready, timeout=3)
            html_content = ray.get(ready[0])
        except ray.exceptions.TaskCancelledError:
            print(f"Task was cancelled: {task['tid']}")
            await log["reports"].find_one_and_update(
                {"tid": task["tid"]},
                {
                    "$set": {
                        "status": 0,
                    },
                },
            )
            await cache.ltrim("task_refs", 1, 0)
            return
        fs = AsyncIOMotorGridFSBucket(log)

        filename = f"report_{dataset_id}.html"

        file_id = await fs.upload_from_stream(
            filename,
            html_content.encode(),
            metadata={"contentType": "text/plain"},
        )

        collection = str(task["tid"]) if external else dataset_id
        await log["reports"].find_one_and_update(
            {"tid": task["tid"]},
            {
                "$set": {
                    "collection": collection,
                    "file_id": str(file_id),
                    "filename": filename,
                    "modified": datetime.now(),
                    "status": 2,
                }
            },
        )
        await cache.ltrim("task_refs", 1, 0)
        await queue.rpop("task_queue")

        task_timer = time.time() - task_timer
        print(f">> Process time: {convert_sec_to_hms(int(task_timer))}")
    print(">>> Finished <<<")


async def run_outlier_detection_tasks(
    scan: AsyncIOMotorDatabase,
    log: AsyncIOMotorDatabase,
    queue: Redis,
    cache: Redis,
    task_id: str | None = None,
) -> None:
    if task_id:
        tasks = [await log["outliers"].find_one({"tid": task_id})]
    else:
        tasks = await log["outliers"].find({"status": {"$lt": 2}}).to_list(length=None)

    for task in tasks:
        tid = str(task.get("tid"))
        await queue.lpush("task_queue", tid)

    while await queue.llen("task_queue") > 0:
        task_timer = time.time()
        data = []
        file = []

        tid = (await queue.lrange("task_queue", -1, -1))[0]
        if not tid:
            continue
        await queue.lrem("task_queue", 1, tid)
        task = await log["outliers"].find_one({"tid": tid})
        dataset_id = task.get("collection")
        options = task.get("options")

        for doc in (
            await scan[dataset_id].find().to_list(length=None)
        ):  # TODO instead of reconstruct a dict list, make the query with required attributes
            sample = {k: float(doc.get(k, 0)) for k in options.get("columns")}
            data.append(sample)
            file.append(doc.get("file"))

        tasks = [
            outlier_detection_task.remote(data, {"detector": options.get("detector")})
        ]

        await log["outliers"].find_one_and_update(
            {"tid": tid},
            {
                "$set": {
                    "status": 1,
                },
            },
        )
        await cache.rpush("task_refs", *[pickle.dumps(task) for task in tasks])
        try:
            ready, not_ready = ray.wait(tasks, timeout=3)
            while not_ready:
                await asyncio.sleep(10)
                ready, not_ready = ray.wait(not_ready, timeout=3)
            label, score = ray.get(ready[0])
        except ray.exceptions.TaskCancelledError:
            print(f"Task was cancelled: {tid}")
            await log["outliers"].find_one_and_update(
                {"tid": tid},
                {
                    "$set": {
                        "status": 0,
                    },
                },
            )
            return

        outliers = pd.DataFrame(
            list(zip(file, label, score)), columns=["file", "label", "score"]
        )
        outliers = outliers[outliers["label"] == 1].drop(["label"], axis=1)
        outliers["collection"] = dataset_id
        await log["outliers"].find_one_and_update(
            {"tid": tid},
            {
                "$set": {
                    "outliers": outliers.to_dict("records"),
                    "modified": datetime.now(),
                    "status": 2,
                },
            },
        )
        await queue.rpop("task_queue")

        task_timer = time.time() - task_timer
        print(f">> Process time: {convert_sec_to_hms(int(task_timer))}")
    print(">>> Finished <<<")


async def run_preprocessing_tasks(
    log: AsyncIOMotorDatabase,
    queue: Redis,
    cache: Redis,
    task_id: str | None = None,
) -> None:
    if task_id:
        tasks = [await log["preprocessings"].find_one({"tid": task_id})]
    else:
        tasks = (
            await log["preprocessings"]
            .find({"status": {"$lt": 2}})
            .to_list(length=None)
        )

    for task in tasks:
        tid = str(task.get("tid"))
        await queue.lpush("task_queue", tid)

    while await queue.llen("task_queue") > 0:
        task_timer = time.time()
        file_total = 0
        file_count = 0
        tasks = []
        file_globs = []

        tid = (await queue.lrange("task_queue", -1, -1))[0]
        if not tid:
            continue
        await queue.lrem("task_queue", 1, tid)
        task = await log["preprocessings"].find_one({"tid": tid})

        slash = "" if task.get("source").endswith("/") else "/"
        for ext in extend(task.get("input_format")):
            file_total += len(
                glob.glob(task.get("source") + f"{slash}**/*." + ext, recursive=True)
            )
        for ext in extend(task.get("input_format")):
            file_globs.append(
                glob.iglob(task.get("source") + f"{slash}**/*." + ext, recursive=True)
            )
        if not await queue.exists(tid):
            await queue.set(tid, TaskQueue(total=file_total).model_dump_json())

        output_dir = task.get("source") + "/" + tid
        config = {
            "frac": task["options"].get("scale"),
            "width": task["options"].get("resize"),
            "mode": task["options"].get("mode"),
            "target": task["options"].get("convert"),
            "pattern": task["options"].get("pattern"),
        }

        with Progress(
            SpinnerColumn(), MofNCompleteColumn(), *Progress.get_default_columns()
        ) as p:
            task_progress = p.add_task("[cyan]Sending task...", total=file_total)
            for files in file_globs:
                for path in files:
                    file_count += 1
                    p.update(task_progress, advance=1)
                    # Check if path name matches the pattern
                    try:
                        tasks.append(
                            preprocess_task.remote(
                                path,
                                output_dir,
                                config,
                            )
                        )
                    except Exception as e:
                        print(f"Preprocessing task failed: {e}")
                    if p.finished:
                        break
                if p.finished:
                    break
            await log["preprocessings"].find_one_and_update(
                {"tid": tid},
                {
                    "$set": {
                        "status": 1,
                    },
                },
            )
            await cache.rpush("task_refs", *[pickle.dumps(task) for task in tasks])

        eta_step = 100  # ETA estimation interval
        counter = 0
        ready, not_ready = ray.wait(tasks)

        with Progress(
            SpinnerColumn(), MofNCompleteColumn(), *Progress.get_default_columns()
        ) as p:
            task_progress = p.add_task("[cyan]Processing...\n", total=file_total)
            while not p.finished:
                scan_timer = time.time()
                if len(not_ready) < eta_step:
                    p.update(task_progress, completed=file_total)
                    continue
                tasks = not_ready

                try:
                    ready, not_ready = ray.wait(tasks, num_returns=eta_step, timeout=3)
                except ray.exceptions.TaskCancelledError:
                    print(f"Task was cancelled: {task['tid']}")
                    await log["preprocessings"].find_one_and_update(
                        {"tid": tid},
                        {
                            "$set": {
                                "status": 0,
                            },
                        },
                    )
                    await cache.ltrim("task_refs", 1, 0)
                    return
                p.update(task_progress, advance=len(ready))
                counter += len(ready)

                scan_timer = time.time() - scan_timer
                elapse = time.time() - task_timer
                status = json.loads(await queue.get(tid))
                status["done"] = counter
                throughput = status["done"] / elapse
                eta = (status["total"] - status["done"]) / throughput
                status["eta"] = int(eta)
                print(f">> Finished: {counter}/{status['total']}")
                print(f">> Elapsed: {convert_sec_to_hms(int(elapse))}")
                print(f">> ETA: {convert_sec_to_hms(int(eta))}")
                print(f">> Throughput: {throughput:.2f} items/s\n")
                await queue.set(tid, json.dumps(status))

        ray.get(tasks)
        print("Finished!")

        task_timer = time.time() - task_timer

        await log["preprocessings"].find_one_and_update(
            {"tid": tid},
            {
                "$set": {
                    "target": output_dir,
                    "modified": datetime.now(),
                    "status": 2,
                },
            },
        )
        await cache.ltrim("task_refs", 1, 0)
        await queue.rpop("task_queue")
        await queue.delete(tid)

        print(f">> File count: {file_count}")
        print(f">> Throughput: {(file_count/task_timer):.2f} items/s")
        print(f">> Process time: {convert_sec_to_hms(int(task_timer))}")
        print(f">> Output: {output_dir}")
    print(">>> Finished <<<")


async def run_test_tasks() -> str:
    out = subprocess.run(
        ["python3", "-m", "pytest", "tests", "-v"], capture_output=True
    )
    return out.stdout.decode()


def get_files(
    folder,
    ext=["jpg", "jpeg", "png", "bmp", "wsq", "jp2", "wav"],
    pattern=None,
) -> list:
    slash = "" if folder.endswith("/") else "/"
    file_globs = []
    files = []
    if extended(ext):
        for extention in extended(ext):
            file_globs.append(
                glob.iglob(folder + f"{slash}**/*." + extention, recursive=True)
            )
        for file_glob in file_globs:
            for file in file_glob:
                if pattern is None or re.search(
                    pattern, file.split("/")[-1].split(".")[0]
                ):
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
    if modality == "face":
        if not options.get("engine"):
            options["engine"] = "bqat"
        if options["engine"] == "bqat" and not options.get("confidence"):
            options["confidence"] = 0.7
        # elif options["engine"] == "ofiq":
        #     if not options.get("type"):
        #         options.update({"type": "folder"})
        elif options["engine"] == "biqt":
            pass
    elif modality == "fingerprint":
        if not options.get("source") or options.get("source") == "default":
            options["source"] = ["png", "jpg", "jpeg", "bmp", "jp2", "wsq"]
        if not options.get("target") or options.get("target") == "default":
            options["target"] = "png"
    elif modality == "iris":
        pass
    elif modality == "speech":
        if not options.get("type"):
            options.update({"type": "folder"})
        if options.get("type") != "folder":
            options.update({"type": "folder"})
    else:
        return False
    return options


def generate_report(data, **options):
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_file = Path(tmpdir) / f"{uuid4()}.html"

        df = pd.DataFrame.from_dict(data)

        excluded_columns = ["file", "tag", "log"]
        excluded_columns = [col for col in excluded_columns if col in df.columns]

        df = df.drop(columns=excluded_columns)
        df = df.loc[:, ~df.columns.str.endswith("_scalar")]

        # Replace nan with numpy.nan
        df = df.replace("nan", np.nan)

        # Ensure numeric columns are not categorized
        tmp = df.apply(lambda col: pd.to_numeric(col, errors="coerce"))
        df = tmp.fillna(df)

        numeric_columns = df.select_dtypes(include="number").columns
        df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric, downcast="float")

        if options.get("downsample"):
            df = df.sample(frac=options.get("downsample", 0.05))

        # Convert specified columns to categorical values
        cat_cols = ("roll_pose", "pitch_pose", "yaw_pose")
        for col in df.columns:
            if col not in excluded_columns and col in cat_cols:
                df[col] = df[col].astype("category")

        match options.get("mode"):
            case "face":
                match options.get("engine"):
                    case "bqat":
                        descriptions = {item.name: item.value for item in FaceSpecBQAT}
                        metadata = {
                            "description": "Face image dataset, processed by BQAT engine."
                        }
                    case "ofiq":
                        descriptions = {item.name: item.value for item in FaceSpecOFIQ}
                        metadata = {
                            "description": "Face image dataset, processed by OFIQ engine."
                        }
                    case "biqt":
                        descriptions = {item.name: item.value for item in FaceSpecBIQT}
                        metadata = {
                            "description": "Face image dataset, processed by BIQT engine."
                        }
                    case _:
                        descriptions = {}
                        metadata = {"description": "Face image dataset."}
            case "fingerprint":
                descriptions = {
                    item.name: item.value for item in FingerprintSpecDefault
                }
                metadata = {"description": "Fingerprint image dataset."}
            case "iris":
                descriptions = {item.name: item.value for item in IrisSpecDefault}
                metadata = {"description": "Iris image dataset."}
            case "speech":
                descriptions = {item.name: item.value for item in SpeechSpecDefault}
                metadata = {"description": "Audio file dataset."}
            case _:
                descriptions = {}
                metadata = {"description": "Not available."}

        pd.set_option("display.float_format", "{:.4f}".format)

        ProfileReport(
            df,
            title=f"EDA Report (BQAT v{__version__})",
            dataset=metadata,
            explorative=True,
            minimal=options.get("minimal", False),
            # progress_bar=False,
            correlations={
                "auto": {"calculate": False},
                "pearson": {"calculate": True},
                "spearman": {"calculate": True},
                "kendall": {"calculate": True},
                "phi_k": {"calculate": False},
                "cramers": {"calculate": False},
            },
            # correlations=None,
            vars={"num": {"low_categorical_threshold": 0}},
            html={
                "navbar_show": True,
                # "full_width": True,
                "style": {
                    "theme": "simplex",
                    "logo": "https://www.biometix.com/wp-content/uploads/2020/10/logo.png",
                },
            },
            variables={"descriptions": descriptions},
        ).to_file(temp_file)

        with open(temp_file, "r") as f:
            html = f.read()

    return html


async def retrieve_report(file_id, db):
    fs = AsyncIOMotorGridFSBucket(db)
    file = open("myfile", "wb+")
    await fs.download_to_stream(PydanticObjectId(file_id), file)
    file.seek(0)
    return file.read()


async def remove_report(file_id, db):
    fs = AsyncIOMotorGridFSBucket(db)
    await fs.delete(PydanticObjectId(file_id))


def get_info():
    return {"backend": __name__, "version": __version__}


def get_tag(identifier):
    tag = hashlib.sha1()
    tag.update(identifier.encode())
    return tag.hexdigest()


def get_outliers(data: list, detector: str = "ECOD"):
    match detector:
        case "ECOD":
            clf = ECOD(n_jobs=-1)
        case "CBLOF":
            clf = CBLOF(n_jobs=-1)
        case "IForest":
            clf = IForest(n_jobs=-1)
        case "KNN":
            clf = KNN(n_jobs=-1)
        case "COPOD":
            clf = COPOD(n_jobs=-1)
        case "PCA":
            clf = PCA()
        # case "DeepSVDD":
        #     clf = DeepSVDD()
        # case "DIF":
        #     clf = DIF()
        case _:
            print(f"detector: {detector} not recognized, fallback to ECOD.")
            clf = ECOD(n_jobs=-1)

    clf.fit(pd.DataFrame.from_records(data))
    labels = clf.labels_
    scores = clf.decision_scores_
    return labels, scores


def extend(suffixes: list):
    suffixes = [s.casefold() for s in suffixes]
    full_ext_list = []
    for s in suffixes:
        full_ext_list.append(s.capitalize())
        full_ext_list.append(s.upper())
        full_ext_list.append(s)
    return full_ext_list


def split_input_folder(
    input_folder,
    temp_folder,
    batch_size=30,
    exts=["jpg", "jpeg", "png", "bmp", "wsq", "jp2"],
    pattern="",
) -> list:
    if not os.path.isdir(input_folder) or not os.path.isdir(temp_folder):
        raise ValueError("Input folder is invalid")
    files = [
        file
        for ext in extended(exts)
        for file in Path(input_folder).rglob(f"*.{ext}")
        if len(pattern) == 0 or re.search(pattern, file.split("/")[-1].split(".")[0])
    ]
    n_files = len(files)
    batch_size = batch_size if n_files > batch_size else n_files
    batches = (
        (n_files // batch_size) + 1
        if n_files % batch_size != 0
        else n_files // batch_size
    )
    subfolders = []
    for i in range(batches):
        subfolder = Path(temp_folder) / f"batch_{i + 1}"
        subfolder.mkdir(exist_ok=False)
        subfolders.append(str(subfolder))
        start = i * batch_size
        end = start + batch_size
        [
            shutil.copyfile(
                file,
                subfolder
                / f"{Path(file).parent.as_posix().replace('/','.')}.{Path(file).name}",
            )
            for file in files[start:end]
        ]
    return subfolders


def convert_sec_to_hms(seconds: int) -> str:
    t_min, t_sec = divmod(seconds, 60)
    t_hr, t_min = divmod(t_min, 60)
    return f"{int(t_hr)}h{int(t_min)}m{int(t_sec)}s"


def ensure_base64_padding(base64_bytes):
    """Ensure the Base64 byte string has proper padding."""
    if isinstance(base64_bytes, str):
        base64_bytes = base64_bytes.encode("utf-8")
    missing_padding = len(base64_bytes) % 4
    if missing_padding:
        base64_bytes += b"=" * (4 - missing_padding)  # Use bytes for padding
    return base64_bytes
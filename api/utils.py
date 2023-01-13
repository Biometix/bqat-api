import glob
import os
import hashlib
import json
import time
from datetime import datetime
import pandas as pd
from pandas_profiling import ProfileReport

import ray
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from redis.asyncio.client import Redis

from api.config.models import CollectionLog, Status, TaskQueue
from bqat.bqat_core import scan


@ray.remote
def scan_task(path, options):
    try:
        result = scan(path, **options)
    except Exception as e:
        print(f">>>> File scan error: {str(e)}")
        log = {"file": path, "error": str(e)}
        return log
    return result


@ray.remote
def report_task(data, options):
    try:
        report = get_report(data, **options)
    except Exception as e:
        print(f">>>> Report generation failed: {str(e)}")
        log = {"options": options, "error": str(e)}
        return log
    return report


async def run_scan_tasks(scan: AsyncIOMotorDatabase, log: AsyncIOMotorDatabase, queue: Redis) -> None:
    tasks = await log["task"].find({"status": {"$lt": 2}}).to_list(length=None)
    for task in tasks:
        tid = str(task.get("tid"))
        await queue.lpush("task_queue", tid)
        if not await queue.exists(tid):
            await queue.set(
                tid,
                json.dumps(
                    TaskQueue(
                        total=len(task.get("input")),
                        done=len(task.get("finished")),
                        eta=0
                    ).dict()
                )
            )
    
    task_timer = time.time()
    file_count = 0
    tasks = []
    
    while await queue.llen("task_queue") > 0:
        tid = (await queue.lrange("task_queue", -1, -1))[0]
        task = await log["task"].find_one({"tid": tid})
        options = task.get("options")
        collection = task.get("collection")
        all_files = set(task.get("input"))
        finished = set(task.get("finished"))
        pending = all_files.difference(finished)
        if task.get("status") == Status.new:
            if not await log["dataset"].find_one({"collection": collection}):
                await CollectionLog(
                    collection=collection
                ).create()
        
        task = await log["task"].find_one_and_update(
            {"tid": tid},
            {"$set": {"status": 1}}
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

        with Progress(
            SpinnerColumn(), MofNCompleteColumn(), *Progress.get_default_columns()
        ) as p:
            task_progress = p.add_task("[cyan]Scanning...", total=len(pending))
            while not p.finished:
                scan_timer = time.time()
                ready, not_ready = ray.wait(tasks, timeout=5)
                scan_timer = time.time() - scan_timer
                p.update(task_progress, advance=len(ready))
                results = ray.get(ready)
                await scan[collection].insert_many(results)
                files = [entry["file"] for entry in results]
                task = await log["task"].find_one_and_update(
                    {"tid": tid},
                    {
                        "$inc": {"elapse": scan_timer},
                        "$addToSet": {"finished": {"$each": files}}
                    }
                )
                await log["dataset"].find_one_and_update(
                    {"collection": collection},
                    {
                        "$set": {"modified": datetime.now()},
                        "$addToSet": {"samples": {"$each": files}}
                    }
                )
                elapse = task.get("elapse") + scan_timer
                status = json.loads(await queue.get(tid))
                status["done"] += len(files)
                eta = elapse/status["done"]*(status["total"] - status["done"])
                status["eta"] = eta
                t_min, t_sec = divmod(eta, 60)
                t_hr, t_min = divmod(t_min, 60)
                print(f">> ETA: {int(t_hr)}h{int(t_min)}m{int(t_sec)}s")
                await queue.set(tid, json.dumps(status))
                tasks = not_ready
                if not len(task):
                    break
    
        task = await log["task"].find_one({"tid": tid})
        if task and (len(task.get("input")) <= len(task.get("finished"))):
            await log["task"].find_one_and_update(
                {"tid": tid},
                {"$set": {"status": 2}}
            )
            await queue.rpop("task_queue")
            await queue.delete(tid)

    task_timer = time.time() - task_timer
    t_min, t_sec = divmod(task_timer, 60)
    t_hr, t_min = divmod(t_min, 60)
    print(f">> File count: {file_count}")
    print(f">> Throughput: {(task_timer/file_count):.2f}s/item")
    print(f">> Process time: {int(t_hr)}h{int(t_min)}m{int(t_sec)}s")
    print(">>> Finished <<<")


# async def run_scan_tasks(db: AsyncIOMotorDatabase, log: AsyncIOMotorDatabase, queue: Redis) -> None:
#     tasks = await log["task"].find({"status": {"$lt": 2}}).to_list(length=None)
#     for task in tasks:
#         tid = str(task.get("tid"))
#         await queue.lpush("task_queue", tid)
#         if not await queue.exists(tid):
#             await queue.set(
#                 tid,
#                 json.dumps(
#                     TaskQueue(
#                         total=len(task.get("input")),
#                         done=len(task.get("finished")),
#                         eta=0
#                     ).dict()
#                 )
#             )

#     while await queue.llen("task_queue") > 0:
#         tid = (await queue.lrange("task_queue", -1, -1))[0]
#         task = await log["task"].find_one({"tid": tid})
#         options = task.get("options")
#         collection = task.get("collection")
#         all_files = set(task.get("input"))
#         finished = set(task.get("finished"))
#         pending = all_files.difference(finished)
#         [await queue.lpush("scan_queue", file) for file in pending]
#         if task.get("status") == Status.new:
#             if not await log["dataset"].find_one({"collection": collection}):
#                 await CollectionLog(
#                     collection=collection
#                 ).create()
#         file_count = 0
#         task_timer = time.time()
#         while await queue.llen("scan_queue") > 0:
#             file = await queue.rpop("scan_queue")
#             file_count += 1
#             print(f"=== File #{file_count} ===")
#             print(f">> Input: {file}")
#             scan_timer = time.time()
#             scan = scan_task.remote(file, options)
#             result = ray.get(scan)
#             # ray.shutdown()
#             print(f">> Done!\n")
#             scan_timer = time.time() - scan_timer
#             await db[collection].insert_one(result)
#             task = await log["task"].find_one_and_update(
#                 {"tid": tid},
#                 {
#                     "$inc": {"elapse": scan_timer},
#                     "$set": {"status": 1},
#                     "$push": {"finished": file}
#                 }
#             )
#             await log["dataset"].find_one_and_update(
#                 {"collection": collection},
#                 {
#                     "$set": {"modified": datetime.now()},
#                     "$push": {"samples": file}
#                 }
#             )
#             elapse = task.get("elapse") + scan_timer
#             status = json.loads(await queue.get(tid))
#             status["done"] += 1
#             status["eta"] = elapse/status["done"]*(status["total"] - status["done"])
#             await queue.set(tid, json.dumps(status))

#         task = await log["task"].find_one({"tid": tid})
#         if task and (len(task.get("input")) <= len(task.get("finished"))):
#             await log["task"].find_one_and_update(
#                 {"tid": tid},
#                 {"$set": {"status": 2}}
#             )
#             await queue.rpop("task_queue")
#             await queue.delete(tid)

#         task_timer = time.time() - task_timer
#         t_min, t_sec = divmod(task_timer, 60)
#         t_hr, t_min = divmod(t_min, 60)
#         print(f">> File count: {file_count}")
#         print(f">> Throughput: {(task_timer/file_count):.2f}s/item")
#         print(f">> Process time: {int(t_hr)}h{int(t_min)}m{int(t_sec)}s")
#         print(">>> Finished <<<")


async def run_report_tasks(scan: AsyncIOMotorDatabase, log: AsyncIOMotorDatabase) -> None:
    tasks = []
    for task in await log["report"].find().to_list(length=None):
        if not task.get("html"):
            tasks.append(task)

    for task in tasks:
        task_timer = time.time()
        data = []
        dataset_id = task.get("collection")
        print(f">> Generate report: {dataset_id}")
        for doc in await scan[dataset_id].find().to_list(length=None):
            doc.pop("_id")
            data.append(doc)
        report = report_task.remote(data, task.get("options"))
        html_content = ray.get(report)
        await log["report"].find_one_and_update(
                {"collection": dataset_id},
                {
                    "$set": {"html": html_content}
                }
            )
        task_timer = time.time() - task_timer
        t_min, t_sec = divmod(task_timer, 60)
        t_hr, t_min = divmod(t_min, 60)
        print(f">> Process time: {int(t_hr)}h{int(t_min)}m{int(t_sec)}s")
    print(">>> Finished <<<")



def get_files(folder, ext=("jpg", "jpeg", "png", "bmp", "wsq", "jp2")) -> list:
    file_globs = []
    files = []
    for ext in extended(ext):
        file_globs.append(glob.iglob(folder + '**/*.' + ext, recursive=True))
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
    else:
        return False
    return options


def get_report(data, **options):
    temp="report.html"
    df = pd.DataFrame.from_dict(data)
    # df.set_index("file", inplace=True)
    # df = df.drop(columns=['file'])
    if options.get("downsample"):
        df = df.sample(frac=options.get("frac", 0.05))
    report = ProfileReport(
        df,
        title="Biometric Quality Report",
        explorative=True,
        minimal=options.get("minimal", True),
        correlations={"cramers": {"calculate": False}},
        html={"style": {"theme": "flatly"}},
    )
    report.to_file(temp)

    with open(temp, 'r') as f:
        html = f.read()
    os.remove(temp)

    return html

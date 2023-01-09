import glob
import hashlib
import json
import time
from datetime import datetime

import ray
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from redis.asyncio.client import Redis

from api.config.models import CollectionLog, Status, TaskQueue
from bqat.bqat_core import scan

EXT = ("jpg", "jpeg", "png", "bmp")


@ray.remote
def scan_task(path, mode):
    try:
        result = scan(path, mode)
    except Exception as e:
        print(f">>>> File scan error: {str(e)}")
        log = {"file": path, "error": str(e)}
        return log
    return result


async def run_tasks(db: AsyncIOMotorDatabase, log: AsyncIOMotorDatabase, queue: Redis) -> None:
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

    while await queue.llen("task_queue") > 0:
        tid = (await queue.lrange("task_queue", -1, -1))[0]
        task = await log["task"].find_one({"tid": tid})
        options = task.get("options")
        collection = task.get("collection")
        all_files = set(task.get("input"))
        finished = set(task.get("finished"))
        pending = all_files.difference(finished)
        [await queue.lpush("scan_queue", file) for file in pending]
        if task.get("status") == Status.new:
            if not await log["dataset"].find_one({"collection": collection}):
                await CollectionLog(
                    collection=collection
                ).create()
        file_count = 0
        task_timer = time.time()
        while await queue.llen("scan_queue") > 0:
            file = await queue.rpop("scan_queue")
            file_count += 1
            print(f"=== File #{file_count} ===")
            print(f">> Input: {file}\n")
            scan_timer = time.time()
            scan = scan_task.remote(file, options)
            result = ray.get(scan)
            ray.shutdown()
            scan_timer = time.time() - scan_timer
            await db[collection].insert_one(result)
            task = await log["task"].find_one_and_update(
                {"tid": tid},
                {
                    "$inc": {"elapse": scan_timer},
                    "$set": {"status": 1},
                    "$push": {"finished": file}
                }
            )
            await log["dataset"].find_one_and_update(
                {"collection": collection},
                {
                    "$set": {"modified": datetime.now()},
                    "$push": {"samples": file}
                }
            )
            elapse = task.get("elapse") + scan_timer
            status = json.loads(await queue.get(tid))
            status["done"] += 1
            status["eta"] = elapse/status["done"]*(status["total"] - status["done"])
            await queue.set(tid, json.dumps(status))

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


def get_files(folder) -> list:
    file_globs = []
    files = []
    for ext in extended(EXT):
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

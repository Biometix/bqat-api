# import os
from contextlib import asynccontextmanager

import uvicorn
from beanie import init_beanie
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from redis import asyncio as aioredis

from api.config import Settings
from api.config.models import (
    CollectionLog,
    OutlierDetectionLog,
    PreprocessingLog,
    ReportLog,
    SampleLog,
    TaskLog,
)
from api.routes.index import router as bqat_index
from api.routes.scan import router as bqat_scan
from api.routes.task import router as bqat_task

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.mongodb_client = AsyncIOMotorClient(settings.MGO_URL)
        app.scan = app.mongodb_client[settings.SCAN_DB]
        app.log = app.mongodb_client[settings.LOG_DB]
        if await app.mongodb_client.server_info():
            print(f"Connect to MongoDB (scan): {app.scan.name}")
        await init_beanie(
            database=app.log,
            document_models=[
                TaskLog,
                CollectionLog,
                ReportLog,
                SampleLog,
                OutlierDetectionLog,
                PreprocessingLog,
            ],
        )
        print(f"Connect to MongoDB (log): {app.log.name}")
    except Exception as e:
        print(f"Failed to connect MongoDB: {str(e)}")

    try:
        app.queue = aioredis.from_url(
            url=settings.RDS_URL, db=settings.QUEUE_DB, decode_responses=True
        )
        if await app.queue.info():
            print(f"Connect to Redis (queue): {settings.QUEUE_DB}")

        app.cache = aioredis.from_url(
            url=settings.RDS_URL, db=settings.CACHE_DB, decode_responses=False
        )
        if await app.cache.info():
            print(f"Connect to Redis (cache): {settings.CACHE_DB}")
    except Exception as e:
        print(f"Failed to connect Redis: {str(e)}")

    # app.mount(
    #     "/data",
    #     StaticFiles(directory=f"{settings.DATA}"),
    #     name="data",
    # )

    yield

    app.mongodb_client.close()
    await app.queue.close()


app = FastAPI(
    title=settings.APP_NAME,
    summary=settings.SUMMARY,
    description=settings.DESCRIPTION,
    version=settings.APP_VERSION,
    contact={
        "name": "Biometix",
        "url": "https://biometix.github.io/",
        "email": "support@biometix.com",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.WEB,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(bqat_scan, tags=["scan"], prefix="/scan")
app.include_router(bqat_task, tags=["task"], prefix="/task")
app.include_router(bqat_index, tags=["index"])


def create_app():
    uvicorn.run(
        "api.app:app",
        host=settings.HOST,
        # workers=os.cpu_count() - 2 if os.cpu_count() > 3 else 1,
        port=settings.PORT,
        reload=settings.DEBUG_MODE,
    )

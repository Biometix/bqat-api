from pydantic_settings import BaseSettings


class CommonSettings(BaseSettings):
    APP_NAME: str = "BQAT-API"
    APP_VERSION: str = "1.4.0-beta"
    SUMMARY: str = "BQAT-API provides access to BQAT functionalities via web APIs. 🚀"
    DESCRIPTION: str = """
## Basic Workflow

1. Create a scan task:

- Create a scan task from the local input folder: (__POST /scan/local__)
- **OR** Create a scan task with files uploaded via HTTP request: (__POST /scan/remote__)

2. Check task status:

- Use (__GET /task/{task_id}/__) to monitor the status of the scan task.

3. Retrieve scan results:

- Once completed, use the dataset id (`collection` id from the scan response) to fetch profiles: (__GET /scan/{dataset_id}/profiles/__)

## Pre-process
+ Preprocess images for scaning:

    1. __POST /scan/preprocess__
    2. __GET /scan/preprocess/{task_id}__

    
## Post-process
+ Generate statistical report for the results:
    1. __POST /scan/{dataset id}/report/generate__
    2. __GET /scan/{dataset id}/report__

+ Detect outliers from the results:
    1. __POST /scan/{dataset id}/outliers/detect__
    2. __GET /scan/{dataset id}/outliers__

"""
    DEBUG_MODE: bool = False
    ACCESSS_KEY: str = "bqat"


class ServerSettings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8848
    WEB: str = "http://localhost:9949"


class DatabaseSettings(BaseSettings):
    MGO_URL: str
    SCAN_DB: str = "scan"
    LOG_DB: str = "log"
    OUTLIER_DB: str = "outlier"
    RDS_URL: str
    QUEUE_DB: int = 10
    CACHE_DB: int = 11
    TEMP: str = "/tmp/bqat/"


class Settings(CommonSettings, ServerSettings, DatabaseSettings):
    DATA: str = "data/"
    CPU_RESERVE_PER_TASK: float = 1.2
    TASK_WAIT_INTERVAL_SLEEP: int = 7  # Sleep time between each task status check
    TASK_WAIT_INTERVAL_TIMEOUT: int = 3  # Timeout for each task status check
    TASK_WAIT_INTERVAL_STEP: int = 30  # Outputs to wait for each task status check

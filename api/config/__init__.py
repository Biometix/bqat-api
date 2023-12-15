from pydantic import BaseSettings


class CommonSettings(BaseSettings):
    APP_NAME: str = "BQAT-API"
    APP_VERSION: str = "1.3.0-beta"
    SUMMARY: str = "BQAT-API provides BQAT functionalities via web APIs. 🚀"
    DESCRIPTION: str = """
## Basic Workflow

1. Create a scan task with your input dataset, the dataset could come from local `data/` folder (__POST /scan/__) or uploaded via the HTTP request (__POST /scan/uploaded__).
2. Note down the task id (`tid`) from the response, and check the status of this task with (__GET /task/{task id}/__).
3. Retrieve the results using dataset id (`collection` id from response above) from the server (__GET /scan/{dataset id}/profiles__).

## Post Process
+ Generate statistical report for the results:
    1. __POST /scan/{dataset id}/report/generate__
    2. __GET /scan/{dataset id}/report__

+ Detect outliers from the results:
    1. __POST /scan/{dataset id}/outliers/detect__
    2. __GET /scan/{dataset id}/outliers__

"""
    DEBUG_MODE: bool = False


class ServerSettings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8848


class DatabaseSettings(BaseSettings):
    MGO_URL: str
    SCAN_DB: str
    LOG_DB: str
    RDS_URL: str
    QUEUE_DB: str
    TEMP: str = "temp/"


class Settings(CommonSettings, ServerSettings, DatabaseSettings):
    pass

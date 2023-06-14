from pydantic import BaseSettings


class CommonSettings(BaseSettings):
    APP_NAME: str = "BQAT"
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

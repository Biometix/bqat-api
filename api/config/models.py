import os
from uuid import UUID, uuid4
from typing import Optional, List
from enum import IntEnum

from datetime import datetime
from beanie import Document
from pydantic import BaseModel, Field, validator


class Metadata(BaseModel):
    result: dict = Field(...)

    class Config:
        schema_extra = {
            "example": {
                "result": {
                        "uuid": "8cea4af7-1670-5752-be3c-b29f49fc039d",
                        "file": "data/input/290349_1.jpg",
                        "size": {
                            "w": 640,
                            "h": 480
                        },
                        "confidence": 0.8088988661766052,
                        "bounding_box": {
                            "left": 400,
                            "upper": 236,
                            "right": 949,
                            "lower": 784
                        },
                        "quality": 10.840662402290349,
                        "iris": {
                            "right": {
                                "x": 329.29288482666016,
                                "y": 144.7666244506836
                            },
                            "left": {
                                "x": 525.2928848266602,
                                "y": 133.7666244506836
                            },
                            "distance": 196.30843079195554
                        },
                        "pose": {
                            "yaw": 8.550166426089962,
                            "pitch": 10.345162966493177,
                            "roll": 0.17792792894149725
                        },
                        "face": {
                            "age": 31,
                            "region": {
                                "x": 153.29288482666016,
                                "y": -43.233375549316406,
                                "w": 519.3915939331055,
                                "h": 519.330940246582
                            },
                            "gender": "Woman",
                            "race": {
                                "asian": 0.07008204702287912,
                                "indian": 0.05094942171126604,
                                "black": 0.0026142395654460415,
                                "white": 89.63627219200134,
                                "middle eastern": 4.752367734909058,
                                "latino hispanic": 5.487718433141708
                            },
                            "dominant_race": "white",
                            "emotion": {
                                "angry": 1.8645887443178144,
                                "disgust": 0.00165702359353845,
                                "fear": 0.45946317669529774,
                                "happy": 96.802466917185,
                                "sad": 0.2219966512245924,
                                "surprise": 0.35268785205858066,
                                "neutral": 0.2971398588427817
                            },
                            "dominant_emotion": "happy"
                        }
                    }
            }
        }


class Options(BaseModel):
    quality: bool = True
    head: bool = True
    face: bool = True
    confidence: float = Field(
        0.7,
        title='Confidence Level',
        description='This is the confidence level of face detection',
        gt=0,
        lt=.99
    )

    @validator('confidence')
    def confidence_level_must_be_legal(cls, v):
        if v < 0 or v > 1:
            raise ValueError('confidence value illegal')
        return v


class Folder(BaseModel):
    path: str = Field(...)
    collection: str = Field(...)

    @validator('path')
    def folder_must_exist(cls, v):
        if not os.path.exists(v):
            raise ValueError(f"folder '{v}' not exist")
        if not os.path.isdir(v):
            raise ValueError(f"path to '{v}' is not a folder")
        return v

    class Config:
        schema_extra = {
            "example": {
                "path": "data/helen/",
                "collection": "7dc79c8f-855a-42c8-8628-bff4d9ac66e4"
            }
        }


class FileList(BaseModel):
    files: List[str] = Field(...)
    collection: str = Field(...)

    @validator('files')
    def path_must_exist(cls, files):
        for v in files:
            if not os.path.exists(v):
                raise ValueError(f"file '{v}' not exist")
        return files

    class Config:
        schema_extra = {
            "example": {
                "files": [
                    "data/helen/20301003_1.jpg",
                    "data/helen/20315024_1.jpg",
                    "data/helen/17349955_1.jpg"
                ],
                "collection": "2e7f31ef-cba8-4365-856e-38b0621a6041"
            }
        }


class ScanEdit(BaseModel):
    pitch: Optional[float]
    yaw: Optional[float]
    roll: Optional[float]
    age: Optional[int]
    race: Optional[str]
    gender: Optional[str]
    emotion: Optional[str]
    quality: Optional[float]

    @validator('quality')
    def quality_must_be_legal(cls, v):
        if v < 0 or v > 100:
            raise ValueError('quality value illegal')
        return v

    @validator('pitch')
    def pitch_must_be_legal(cls, v):
        if v < -90 or v > 90:
            raise ValueError('angle value illegal')
        return v
    
    @validator('yaw')
    def yaw_must_be_legal(cls, v):
        if v < -90 or v > 90:
            raise ValueError('angle value illegal')
        return v
    
    @validator('roll')
    def roll_must_be_legal(cls, v):
        if v < -90 or v > 90:
            raise ValueError('angle value illegal')
        return v
    
    @validator('age')
    def age_must_be_legal(cls, v):
        if v < 0 or v > 200:
            raise ValueError('age value illegal')
        return v
    
    @validator('gender')
    def gender_must_be_legal(cls, v):
        gender_list = (
            "Woman",
            "Man"
        )
        if v not in gender_list:
            raise ValueError('gender value not found')
        return v
    
    @validator('race')
    def race_must_be_legal(cls, v):
        race_list = (
            "asian", "indian",
            "black", "white",
            "middle eastern", "latino hispanic"
        )
        if v not in race_list:
            raise ValueError('race value not found')
        return v
    
    @validator('emotion')
    def emotion_must_be_legal(cls, v):
        race_list = (
            "angry", "disgust",
            "fear", "happy",
            "sad", "surprise",
            "neutral"
        )
        if v not in race_list:
            raise ValueError('emotion value not found')
        return v

    class Config:
        schema_extra = {
            "example": {
                "yaw": 8.550166426089962,
                "pitch": 10.345162966493177,
                "roll": 0.17792792894149725,
                "age": 31,
                "gender": "Woman",
                "race": "white",
                "emotion": "happy",
                "quality": 24.8
            }
        }


class MetadataList(BaseModel):
    results: List[Metadata]


class Status(IntEnum):
    new = 0
    running = 1
    done = 2


class TaskLog(Document):
    tid: UUID = Field(default_factory=uuid4)
    input: List[str]
    options: Options = Options()
    collection: UUID = Field(default_factory=uuid4)
    status: Status = Status.new
    finished: List[str] = []
    elapse: int = 0

    class Settings:
        name = "task"
        bson_encoders = {
            UUID: str
        }

    class Config:
        schema_extra = {
            "example": {
                "input": [
                    "data/helen/20301003_1.jpg",
                    "data/helen/20315024_1.jpg",
                    "data/helen/17349955_1.jpg"
                ],
                "options": {
                    "quality": False,
                    "head": True,
                    "face": True,
                    "confidence": 0.6
                },
                "collection": "8692d82d-ff5f-485e-8189-5e62e60858c9",
            }
        }


class EditTaskLog(BaseModel):
    input: Optional[List[str]]
    finished: Optional[List[str]]
    options: Optional[Options]
    collection: Optional[str]
    status: Optional[Status]
    elapse: Optional[int]

    class Config:
        schema_extra = {
            "example": {
                "input": [
                    "data/input/106242334_1.jpg",
                    "data/input/108349477_1.jpg",
                    "data/input/109172267_1.jpg"
                ],
                "finished": [
                    "data/input/109172267_1.jpg"
                ],
                "options": {
                    "quality": False,
                    "head": True,
                    "face": True,
                    "confidence": 0.6
                },
                "collection": "8692d82d-ff5f-485e-8189-5e62e60858c9",
                "status": 1,
                "eta": 7200
            }
        }


class CollectionLog(Document):
    collection: str
    created: datetime = Field(default_factory=datetime.utcnow)
    modified: datetime = created
    samples: List[str] = []

    class Settings:
        name = "dataset"

    class Config:
        schema_extra = {
            "example": {
                "collection": "8692d82d-ff5f-485e-8189-5e62e60858c9",
                "samples": [
                    "data/helen/20301003_1.jpg",
                    "data/helen/20315024_1.jpg",
                    "data/helen/17349955_1.jpg"
                ]
            }
        }


class EditCollectionLog(BaseModel):
    collection: Optional[str]
    modified: Optional[datetime]
    files: Optional[List[str]]

    class Config:
        schema_extra = {
            "example": {
                "samples": [
                    "data/input/106242334_1.jpg",
                    "data/input/108349477_1.jpg",
                    "data/input/109172267_1.jpg"
                ]
            }
        }


class TaskQueue(BaseModel):
    total: int
    done: int = 0
    eta: float = 0.0

    class Config:
        schema_extra = {
            "example": {
                "total": 100,
                "done": 45,
                "eta": 7200
            }
        }


# def ResponseModel(data, message):
#     return {
#         "data": [data],
#         "code": 200,
#         "message": message,
#     }
#
#
# def ErrorResponseModel(error, code, message):
#     return {"error": error, "code": code, "message": message}

import os
from datetime import datetime
from enum import Enum, IntEnum
from typing import List, Optional, Union
from uuid import UUID, uuid4

from beanie import Document
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ImageRequest(BaseModel):
    file: str
    format: str = "webp"

class Metadata(BaseModel):
    result: dict = Field(...)
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "result": {
                    "uuid": "8cea4af7-1670-5752-be3c-b29f49fc039d",
                    "file": "input/face/290349_1.jpg",
                    "size": {"w": 640, "h": 480},
                    "confidence": 0.8088988661766052,
                    "bounding_box": {
                        "left": 400,
                        "upper": 236,
                        "right": 949,
                        "lower": 784,
                    },
                    "quality": 10.840662402290349,
                    "iris": {
                        "right": {"x": 329.29288482666016, "y": 144.7666244506836},
                        "left": {"x": 525.2928848266602, "y": 133.7666244506836},
                        "distance": 196.30843079195554,
                    },
                    "pose": {
                        "yaw": 8.550166426089962,
                        "pitch": 10.345162966493177,
                        "roll": 0.17792792894149725,
                    },
                    "face": {
                        "age": 31,
                        "region": {
                            "x": 153.29288482666016,
                            "y": -43.233375549316406,
                            "w": 519.3915939331055,
                            "h": 519.330940246582,
                        },
                        "gender": "Woman",
                        "race": {
                            "asian": 0.07008204702287912,
                            "indian": 0.05094942171126604,
                            "black": 0.0026142395654460415,
                            "white": 89.63627219200134,
                            "middle eastern": 4.752367734909058,
                            "latino hispanic": 5.487718433141708,
                        },
                        "dominant_race": "white",
                        "emotion": {
                            "angry": 1.8645887443178144,
                            "disgust": 0.00165702359353845,
                            "fear": 0.45946317669529774,
                            "happy": 96.802466917185,
                            "sad": 0.2219966512245924,
                            "surprise": 0.35268785205858066,
                            "neutral": 0.2971398588427817,
                        },
                        "dominant_emotion": "happy",
                    },
                }
            }
        }
    )


class Modality(str, Enum):
    face = "face"
    iris = "iris"
    fingerprint = "fingerprint"
    speech = "speech"


class Engine(str, Enum):
    bqat = "bqat"
    ofiq = "ofiq"
    biqt = "biqt"


class Format(str, Enum):
    png = "png"
    jpeg = "jpeg"
    jpg = "jpg"
    bmp = "bmp"
    jp2 = "jp2"
    wsq = "wsq"
    wav = "wav"


class ColourMode(str, Enum):
    grayscale = "grayscale"
    greyscale = "greyscale"
    bw = "bw"
    rgb = "rgb"
    rgba = "rgba"
    hsv = "hsv"
    cmyk = "cmyk"
    ycbcr = "ycbcr"


class Detector(Enum):
    default = "ECOD"
    ecod = "ECOD"
    cblof = "CBLOF"
    iforest = "IForest"
    knn = "KNN"
    copod = "COPOD"
    pca = "PCA"
    # deepsvdd = "DeepSVDD" # TensorFlow required
    # dif = "DIF" # PyTorch required


class DetectorOptions(BaseModel):
    detector: Detector | None = Detector.ecod
    columns: List[str] | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detector": "ECOD",
                "columns": [
                    "ipd",
                    "yaw_degree",
                    "pitch_degree",
                    "roll_degree",
                ],
            }
        }
    )


class ReportOptions(BaseModel):
    minimal: Union[bool, None] | None = False
    downsample: Union[float, None] | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "minimal": False,
                "downsample": 0.5,
            }
        }
    )


class PreprocessingOptions(BaseModel):
    scale: Union[float, None] = 1.0
    resize: Union[int, None] = None
    convert: Union[Format, None] = None
    mode: Union[ColourMode, None] = None
    pattern: Union[str, None] = None

    @field_validator("scale")
    @classmethod
    def scaler_value_must_legal(cls, v):
        if not v:
            return None
        if v <= 0:
            raise ValueError("scaler value must be positive")
        elif v > 20:
            raise ValueError("scaler value must be less than 10")
        return v

    @field_validator("resize")
    @classmethod
    def resize_value_must_legal(cls, v):
        if not v:
            return None
        if v < 20:
            raise ValueError(
                f"image size (width) must be greater than 20, but {v} given"
            )
        elif v > 10000:
            raise ValueError(
                f"image size (width) must be less than 10000, but {v} given"
            )
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "convert": "png",
                "scale": 0.3,
                "mode": "greyscale",
                "pattern": ".*face.*"
            }
        }
    )


class ScanOptions(BaseModel):
    mode: Union[Modality, None] = None
    engine: Union[Engine, None] = None
    source: Union[List[Format], None] = None
    target: Union[Format, None] = None
    confidence: Union[float, None] = None
    pattern: Union[str, None] = None
    type: Union[str, None] = None
    batch: Union[int, None] = None
    # quality: bool = True
    # head: bool = True
    # face: bool = True


class Folder(BaseModel):
    path: str = Field(...)
    collection: str = Field(...)

    @field_validator("path")
    @classmethod
    def folder_must_exist(cls, v):
        if not os.path.exists(v):
            raise ValueError(f"folder '{v}' not exist")
        if not os.path.isdir(v):
            raise ValueError(f"path to '{v}' is not a folder")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "path": "data/helen/",
                "collection": "7dc79c8f-855a-42c8-8628-bff4d9ac66e4",
            }
        }
    )


class FileList(BaseModel):
    files: List[str] = Field(...)
    collection: str = Field(...)

    @field_validator("files")
    @classmethod
    def path_must_exist(cls, files):
        for v in files:
            if not os.path.exists(v):
                raise ValueError(f"file '{v}' not exist")
        return files

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "files": [
                    "data/helen/20301003_1.jpg",
                    "data/helen/20315024_1.jpg",
                    "data/helen/17349955_1.jpg",
                ],
                "collection": "2e7f31ef-cba8-4365-856e-38b0621a6041",
            }
        }
    )


class ScanTask(BaseModel):
    options: ScanOptions | None = None
    input: Union[List[str], str, None] = Field(...)
    collection: UUID = Field(default_factory=uuid4)

    @field_validator("input")
    @classmethod
    def path_must_exist(cls, input):
        if isinstance(input, str):
            if not os.path.exists(input):
                raise ValueError(f"folder '{input}' not exist")
            if not os.path.isdir(input):
                raise ValueError(f"path to '{input}' is not a folder")
            return input
        elif isinstance(input, List):
            for v in input:
                if not os.path.exists(v):
                    raise ValueError(f"file '{v}' not exist")
            return input

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "options": {
                    "engine": "bqat",
                    "pattern": ".*face.*"
                },
                "input": "data/helen/",
            }
        }
    )


class ScanEdit(BaseModel):
    pitch: Optional[float] = None
    yaw: Optional[float] = None
    roll: Optional[float] = None
    age: Optional[int] = None
    race: Optional[str] = None
    gender: Optional[str] = None
    emotion: Optional[str] = None
    quality: Optional[float] = None

    @field_validator("quality")
    @classmethod
    def quality_must_be_legal(cls, v):
        if v < 0 or v > 100:
            raise ValueError("quality value illegal")
        return v

    @field_validator("pitch")
    @classmethod
    def pitch_must_be_legal(cls, v):
        if v < -90 or v > 90:
            raise ValueError("angle value illegal")
        return v

    @field_validator("yaw")
    @classmethod
    def yaw_must_be_legal(cls, v):
        if v < -90 or v > 90:
            raise ValueError("angle value illegal")
        return v

    @field_validator("roll")
    @classmethod
    def roll_must_be_legal(cls, v):
        if v < -90 or v > 90:
            raise ValueError("angle value illegal")
        return v

    @field_validator("age")
    @classmethod
    def age_must_be_legal(cls, v):
        if v < 0 or v > 200:
            raise ValueError("age value illegal")
        return v

    @field_validator("gender")
    @classmethod
    def gender_must_be_legal(cls, v):
        gender_List = ("Woman", "Man")
        if v not in gender_List:
            raise ValueError("gender value not found")
        return v

    @field_validator("race")
    @classmethod
    def race_must_be_legal(cls, v):
        race_List = (
            "asian",
            "indian",
            "black",
            "white",
            "middle eastern",
            "latino hispanic",
        )
        if v not in race_List:
            raise ValueError("race value not found")
        return v

    @field_validator("emotion")
    @classmethod
    def emotion_must_be_legal(cls, v):
        emotion_List = (
            "angry",
            "disgust",
            "fear",
            "happy",
            "sad",
            "surprise",
            "neutral",
        )
        if v not in emotion_List:
            raise ValueError("emotion value not found")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "yaw": 8.550166426089962,
                "pitch": 10.345162966493177,
                "roll": 0.17792792894149725,
                "age": 31,
                "gender": "Woman",
                "race": "white",
                "emotion": "happy",
                "quality": 24.8,
            }
        }
    )


class MetadataList(BaseModel):
    results: List[Metadata]


class Status(IntEnum):
    new = 0
    running = 1
    done = 2


class ReportLog(Document):
    tid: UUID = Field(default_factory=uuid4)
    collection: Union[UUID, str, None] = None
    external_input: Union[str, None] = None
    options: Union[ReportOptions, None] = ReportOptions()
    file_id: Union[UUID, str, None] = None
    filename: Union[str, None] = None
    modified: datetime = Field(default_factory=datetime.now)
    status: Status = Status.new
    task_refs: Union[List, None] = []

    class Settings:
        name = "reports"
        bson_encoders = {UUID: str}

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "options": {
                    "minimal": True,
                    "downsample": 0.1,
                }
            }
        }
    )


class OutlierDetectionLog(Document):
    tid: UUID = Field(default_factory=uuid4)
    collection: Union[UUID, str, None]
    options: Union[DetectorOptions, None] = DetectorOptions()
    outliers: Union[List, None] = []
    modified: datetime = Field(default_factory=datetime.now)
    status: Status = Status.new
    task_refs: Union[List, None] = None

    class Settings:
        name = "outliers"
        bson_encoders = {UUID: str}

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "options": {
                    "detector": "ECOD",
                    "columns": [
                        "ipd",
                        "yaw_degree",
                        "pitch_degree",
                        "roll_degree",
                    ],
                }
            }
        }
    )


class PreprocessingLog(Document):
    tid: UUID = Field(default_factory=uuid4)
    source: Union[str, None] = None
    target: Union[str, None] = None
    input_format: List = [f.value for f in Format]
    options: PreprocessingOptions = PreprocessingOptions()
    modified: datetime = Field(default_factory=datetime.now)
    status: Status = Status.new
    task_refs: Union[List, None] = []

    class Settings:
        name = "preprocessings"
        bson_encoders = {UUID: str}

    @field_validator("source")
    @classmethod
    def path_must_exist(cls, v):
        if not os.path.exists(v):
            raise ValueError(f"'{v}' not exist")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source": "input/face",
                "options": {
                    "convert": "png",
                    "scale": 0.3,
                    "mode": "greyscale",
                    "pattern": ".*face.*",
                },
            }
        }
    )


class TaskLog(Document):
    tid: UUID = Field(default_factory=uuid4)
    options: Union[dict, None] = None
    collection: UUID = Field(default_factory=uuid4)
    status: Status = Status.new
    input: str = Field(...)
    total: int = Field(...)
    finished: int = 0
    elapse: float = 0.0
    modified: datetime = Field(default_factory=datetime.now)
    task_refs: Union[List, None] = []

    class Settings:
        name = "tasks"
        bson_encoders = {UUID: str}

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "input": "input/face",
                "total": 200,
                "options": {
                    "engine": "bqat",
                    "mode": "face",
                    "confidence": 0.7,
                },
            }
        }
    )


class EditTaskLog(BaseModel):
    input: Optional[str] = None
    total: Optional[int] = None
    finished: Optional[int] = None
    options: Optional[dict] = None
    collection: Optional[str] = None
    status: Optional[Status] = None
    elapse: Optional[int] = None
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "input": "input/face",
                "finished": 100,
                "options": {
                    "engine": "bqat",
                    "mode": "face",
                    "confidence": 0.7,
                },
                "collection": "8692d82d-ff5f-485e-8189-5e62e60858c9",
                "status": 1,
                "eta": 7200,
            }
        }
    )


class CollectionLog(Document):
    collection: str
    options: dict = Field(...)
    created: datetime = Field(default_factory=datetime.now)
    modified: datetime = created
    samples: int = 0

    class Settings:
        name = "datasets"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "collection": "8692d82d-ff5f-485e-8189-5e62e60858c9",
                "options": {
                    "engine": "default",
                    "mode": "face",
                    "confidence": 0.7,
                },
            }
        }
    )


class SampleLog(Document):
    tid: UUID
    collection: str
    path: str
    status: Status = Status.new

    class Settings:
        name = "samples"
        bson_encoders = {UUID: str}

    @field_validator("path")
    @classmethod
    def path_must_exist(cls, path):
        if not os.path.exists(path):
            raise ValueError(f"'{path}' not exist")
        return path


class EditCollectionLog(BaseModel):
    collection: Optional[str] = None
    modified: Optional[datetime] = None
    files: Optional[List[str]] = None
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "samples": 100,
            }
        }
    )


class TaskQueue(BaseModel):
    total: int
    done: int = 0
    eta: int = 0
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total": 100,
                "done": 45,
                "eta": 7200,
            }
        }
    )


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

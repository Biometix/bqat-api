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
    metadata: Union[dict, None] = None
    file_id: Union[UUID, str, None] = None
    filename: Union[str, None] = None
    modified: datetime = Field(default_factory=datetime.now)
    status: Status = Status.new

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
    outliers: Union[str, None] = None
    modified: datetime = Field(default_factory=datetime.now)
    status: Status = Status.new

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


class FaceSpecBQAT(str, Enum):
    ipd = "Inter-pupillary distance."
    confidence = "Confidence level of face dectection (not quality score)."
    bbox_left = "Left border of the face bounding box coordinates in pixels."
    bbox_right = "Right border of the face bounding box coordinates in pixels."
    bbox_upper = "Upper border of the face bounding box coordinates in pixels."
    bbox_bottom = "Bottom border of the face bounding box coordinates in pixels."
    eye_closed_left = "Left eye close or not."
    eye_closed_right = "Right eye close or not."
    pupil_right_x = "X coordinates of right pupil in pixels."
    pupil_right_y = "Y coordinates of right pupil in pixels."
    pupil_left_x = "X coordinates of left pupil in pixels."
    pupil_left_y = "Y coordinates of left pupil in pixels."
    yaw_pose = "Yaw in head pose direction."
    yaw_degree = "Yaw in head pose degree."
    pitch_pose = "Pitch in head pose direction."
    pitch_degree = "Pitch in head pose degree."
    roll_pose = "Roll in head pose direction."
    roll_degree = "Roll in head pose degree."
    smile = "Smile detected or not."
    glassed = "Glasses detected or not."


class FaceSpecOFIQ(str, Enum):
    quality = "MagFace-based unified quality score measure."
    background_uniformity = "Gradient-based background uniformity."
    illumination_uniformity = "Illumination unformity by summing up the minima of the histograms of the left and the right side of the face."
    luminance_mean = "Luminance mean measure computed from the luminance histogram."
    luminance_variance = (
        "Luminance variance measure computed from the luminance histogram."
    )
    under_exposure_prevention = "Under-exposure prevention by computing the proportion of low-intensity pixels in the luminance image to assess the abscence of under-exposure."
    over_exposure_prevention = "Over-exposure prevention by computing the proportion of high-intensity pixels in the luminance image to assess the abscence of over-exposure."
    dynamic_range = "Dynamic range computed from the luminance histogram."
    sharpness = "Sharpness assessment based on a random forest classifier trained by the OFIQ development team."
    compression_artifacts = "Assessment of the absence of compression artifact (both JPEG and JPEG2000) based on a CNN trained by the OFIQ development team."
    natural_colour = "Assessment of the naturalness of the colour based on the conversion of the RGB presentation of the image to the CIELAB colour space."
    single_face_present = "Assessment of the uniqueness of the most dominant face detected by comparing its size with the size of the second largest face detected."
    eyes_open = "Eyes openness assessment based on computing eyes aspect ratio from eye landmarks."
    mouth_closed = (
        "Mouth closed assessment based on computing a ratio from mouth landmarks."
    )
    eyes_visible = "Eyes visibility assessment by measuring the coverage of the eye visibility zone with the result of face occlusion segmentation computed during pre-processing."
    mouth_occlusion_prevention = "Assessment of the absence of mouth occlusion by measuring the coverage of the mouth region from mouth landmarks with the result of face occlusion segmentation computed on pre-processing."
    face_occlusion_prevention = "Assessment of the absence of face occlusion by measuring the coverage of the landmarked region with the result of face occlusion segmentation computed during pre-processing."
    inter_eye_distance = " 	Inter-eye distance assessment based on computing the Euclidean length of eyes’ centres and multiplication with the secant of the yaw angle computed during pre-processing."
    head_size = "Size of the head based on computing the height of the face computed from facial landmarks with the height of the image."
    leftward_crop_of_the_face_image = "Left of the face image crop."
    rightward_crop_of_the_face_image = "Right of the face image crop."
    downward_crop_of_the_face_image = "Bottom of the face image crop."
    upward_crop_of_the_face_image = "Top of the face image crop."
    head_pose_yaw = "Pose angle yaw frontal alignment based on the 3DDFAV2."
    head_pose_pitch = "Pose angle pitch frontal alignment based on the 3DDFAV2."
    head_pose_roll = "Pose angle roll frontal alignment based on the 3DDFAV2."
    expression_neutrality = "Expression neutrality estimation based on a fusion of HSEMotion with Efficient-Expression-Neutrality-Estimation."
    no_head_coverings = "Assessment of the absence of head coverings by counting the pixels being labeled as head covers in the mask output by the face parsing computed during pre-processing."


class FaceSpecBIQT(str, Enum):
    background_deviation = "Image background deviation."
    background_grayness = "Image background grayness."
    blur = "Overall image blurriness."
    blur_face = "Face area blurriness."
    focus = "Overall image focus."
    focus_face = "Face area focus."
    openbr_confidence = "Confidence value from openbr."
    opencv_IPD = "Inter eye distance from opencv."
    over_exposure = "Overall image exposure value."
    over_exposure_face = "Face area exposure value."
    quality = "Overall quality score."
    skin_ratio_face = "Skin to face area ratio."
    skin_ratio_full = "Skin to fill image area ratio."


class FingerprintSpecDefault(str, Enum):
    NFIQ2 = "NIST/NFIQ2 quality score."
    uniform_image = "Standard deviation of gray levels in image indicates uniformity."
    empty_image_or_contrast_too_low = "The image is blank or the contrast is too low."
    fingerprint_image_with_minutiae = "Number of minutia in image."
    sufficient_fingerprint_foreground = "Number of pixels in the computed foreground."
    edge_std = "Metric to identify malformed images."


class IrisSpecDefault(str, Enum):
    quality = "An overall quality score that leverages several statistics together."
    contrast = "Raw score quantifying overall image contrast."
    sharpness = "Raw score quantifying the sharpness of the image."
    iris_diameter = "Raw diameter of the iris measured in pixels."
    percent_visible_iris = "Percentage of visible iris area."
    iris_pupil_gs = "Raw measure quantifying how distinguishable the boundary is between the pupil and the iris."
    iris_sclera_gs = "Raw measure quantifying how distinguishable the boundary is between the iris and the sclera."
    iso_overall_quality = "The overall ISO quality score based on the product of normalized individual iso metrics."
    iso_greyscale_utilization = "The spread of intensity values regarding the pixel values within the iris portion of the image, recommended value: 6 or greater."
    iso_iris_pupil_concentricity = "The degree to which the pupil centre and the iris centre are in the same location, recommended value: 90 or greater."
    iso_iris_pupil_contrast = "The image characteristics at the boundary between the iris region and the pupil, recommended value: 30 or greater."
    iso_iris_pupil_ratio = "The degree to which the pupil is dilated or constricted, recommended value: between 20 and 70."
    iso_iris_sclera_contrast = "The image characteristics at the boundary between the iris region and the sclera, recommended value: greater than 5."
    iso_margin_adequacy = "The degree to which the iris portion of the image is centred relative to the edges of the entire image, recommended value: greater than 80."
    iso_pupil_boundary_circularity = "The circularity of the iris-pupil boundary."
    iso_sharpness = "The degree of focus present in the image."
    iso_usable_iris_area = "The fraction of the iris portion of the image that is not occluded by eyelids, eyelashes, or specular reflections."


class SpeechSpecDefault(str, Enum):
    quality = "Overall quality estimation of the speech audio file."
    noisiness = "Quality degradation such as background, circuit, or coding noise."
    discontinuity = "Quality degradation caused by isolated or non-stationary distortions, e.g. introduced by packet-loss or clipping."
    coloration = "Quality degradation caused by frequency response distortions, e.g. introduced by bandwidth limitation, low bitrate codecs, or packet-loss concealment."
    naturalness = "Estimation of the naturalness of synthetic speech."
    loudness = (
        "Influence of the loudness on the perceived quality of transmitted speech."
    )
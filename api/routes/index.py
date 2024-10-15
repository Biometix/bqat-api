import base64
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from fastapi import APIRouter, Body, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image as PILImage

from api.config import Settings
from api.config.models import ImageRequest
from api.utils import ensure_base64_padding, extend

router = APIRouter()

templates = Jinja2Templates(directory="api/templates")


@router.get(
    f"/warehouse/{Settings().DATA}" + "{dir:path}/",
    response_class=HTMLResponse,
    description="Lists files and directories recursively from a specified directory (Where Docker Mounting Folder). return a html page (files.html) with generates URLs for each file and directory.",
)
def list_dirs(request: Request, dir: str):
    path = Path(Settings().DATA) / dir
    files = path.rglob("*")
    files_paths = sorted(
        [
            f"{request.url._url}{f.relative_to(path)}"
            if f.is_file()
            else f"{request.url._url}{f.relative_to(path)}/"
            for f in files
        ]
    )
    return templates.TemplateResponse(
        "files.html", {"request": request, "files": files_paths, "path": dir}
    )


@router.get(
    f"/warehouse/{Settings().DATA}" + "{path:path}",
    description="Get image or audio files from the data folder.",
)
def get_file(path: str, format: str = "webp"):
    path = Path(Settings().DATA) / path
    if path.suffix in ["." + ext for ext in extend(["wsq", "jp2"])]:
        temp_file = tempfile.SpooledTemporaryFile()
        with PILImage.open(path) as im:
            im.save(temp_file, format)
            temp_file.seek(0)
        return StreamingResponse(
            temp_file,
            media_type=f"image/{format}",
            headers={"Content-Disposition": f"filename={path.stem}"},
        )
    elif path.is_file():
        return FileResponse(path)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found at {path}",
        )


@router.post(
    "/purge",
    response_description="Purge all data stored.",
    description="Deletes all data related to task logs, preprocessing, reports, outliers, and associated files from MongoDB collections and Redis task queue. Clears raw scan output collections in the MongoDB 'scan' database.",
)
async def purge_data(request: Request):
    # Clean up mongo task log collections
    await request.app.log["datasets"].drop()
    await request.app.log["tasks"].drop()
    await request.app.log["samples"].drop()
    await request.app.log["preprocessings"].drop()
    await request.app.log["reports"].drop()
    await request.app.log["outliers"].drop()

    # Clean up mongo report collections
    await request.app.log["fs.files"].delete_many({})
    await request.app.log["fs.chunks"].delete_many({})

    # Clean up redis task queue
    while await request.app.queue.llen("task_queue") > 0:
        tid = await request.app.queue.rpop("task_queue")
        await request.app.queue.delete(tid)

    # Clean up raw scan output collections
    for collection in await request.app.scan.list_collection_names():
        await request.app.scan[collection].drop()

    return {"message": "All data purged."}


# @router.get(
#     "/cwd",
#     response_description="Current working directory printed.",
# )
# async def get_cwd():
#     return Settings().CWD


@router.post(
    "/dataset",
    response_description="Dataset uploaded.",
    description="Uploads a dataset as zip file to the server. The dataset is stored in the 'data' folder and can be accessed via the /data route.",
)
async def upload_dataset(file: UploadFile):
    if file.filename.split(".")[1] != "zip":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please upload dataset in zip archive file.",
        )

    try:
        temp_folder = Path(Settings().DATA) / "uploaded"
        target_folder = temp_folder / file.filename.split(".")[0]
        if target_folder.exists():
            target_folder = (
                temp_folder / f"{file.filename.split('.')[0]}_{str(uuid4())[0:4]}"
            )
        target_folder.mkdir(parents=True, exist_ok=True)

        with open(target_folder / "temp.zip", "wb") as f:
            f.write(await file.read())
        with ZipFile(target_folder / "temp.zip", "r") as z:
            z.extractall(target_folder)

        (target_folder / "temp.zip").unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": f"Dataset uploaded to: {target_folder}"}


@router.post(
    "/convert",
    description="Get converted image files",
)
def get_converted(request: ImageRequest):
    try:
        file = request.file
        format = request.format
        # Validate the format
        valid_formats = ['JPEG', 'PNG', 'GIF', 'BMP', 'TIFF', 'WEBP', 'JP2', 'WSQ']
        if format.upper() not in valid_formats:
            format='webp'

        image_bytes = base64.b64decode(ensure_base64_padding(file))
        # print(f"Image bytes length: {len(image_bytes)}")

        # Load the image from bytes
        with BytesIO(image_bytes) as file:
            with PILImage.open(file) as im:
                max_size = (128, 128)
                im.thumbnail(max_size, PILImage.LANCZOS)

                # Save the resized image to a BytesIO object
                converted = BytesIO()
                im.save(converted, format=format.upper())  # Specify the format for saving

                # Encode the image to Base64
                metaData = f'data:image/{format.lower()};base64,'
                base64_decoded = base64.b64encode(converted.getvalue()).decode('utf-8')
                
                return metaData+base64_decoded 

    except Exception as e:
        print(f'Error processing image: {e}')
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    if Path("favicon.png").exists():
        return FileResponse("favicon.png")
    elif Path("api/favicon.png").exists():
        return FileResponse("api/favicon.png")
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete(
    "/dataset",
    response_description="Dataset deleted.",
    description="Delete a dataset from the server.",
)
async def delete_dataset(
    dataset: Path = Body(...),
):
    try:
        upload_folder = Path(Settings().DATA) / "uploaded"
        if not dataset.is_relative_to(upload_folder):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid dataset path.",
            )
        shutil.rmtree(dataset)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "Dataset deleted"}
import requests
from zipfile import ZipFile
from uuid import UUID, uuid4


BASE = "http://0.0.0.0:8848/"
COLLECTION_1 = str(uuid4())
COLLECTION_2 = str(uuid4())
COLLECTION_3 = str(uuid4())
COLLECTION_4 = str(uuid4())


def test_face_scan_default(tmp_path):
    """
    GIVEN a set of mock face images
    WHEN the images processed by the default engine
    THEN check if the output values are properly generated
    """
    samples = "tests/samples/face.zip"
    with ZipFile(samples, "r") as z:
        input_dir = tmp_path / "input"
        input_dir = str(input_dir) + "/"
        z.extractall(input_dir)

    payload = {
        "options": {
            "engine": "default"
        },
        "input": input_dir,
        "collection": COLLECTION_1
    }
    r = requests.post(BASE + "scan/?modality=face", json=payload)
    tid = r.json().get("tid")
    assert r.status_code == 201
    assert r.headers["content-type"] == "application/json"
    assert list(r.json().keys()) == ["tid"]
    assert isinstance(UUID(tid), UUID)

    r = requests.get(BASE + f"task/{tid}/")
    collection = r.json().get("collection")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert isinstance(UUID(collection), UUID)
    
    r = requests.get(BASE + f"task/{tid}/")
    while r.json().get("status") != 2:
        r = requests.get(BASE + f"task/{tid}/")
    assert r.status_code == 200
    assert r.json().get("input") == r.json().get("finished")

    r = requests.delete(BASE + f"task/{tid}/")
    assert r.status_code == 200


def test_face_outputs_default():
    r = requests.get(BASE + f"scan/logs/{COLLECTION_1}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert r.json().get("samples") == 10

    r = requests.get(BASE + f"scan/{COLLECTION_1}/profiles")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 10


def test_face_scan_alt(tmp_path):
    """
    GIVEN a set of mock face images
    WHEN the images processed by the alternative engine
    THEN check if the output values are properly generated
    """
    samples = "tests/samples/face.zip"
    with ZipFile(samples, "r") as z:
        input_dir = tmp_path / "input"
        input_dir = str(input_dir) + "/"
        z.extractall(input_dir)

    payload = {
        "options": {
            "engine": "biqt"
        },
        "input": input_dir,
        "collection": COLLECTION_2
    }
    r = requests.post(BASE + "scan/?modality=face", json=payload)
    tid = r.json().get("tid")
    assert r.status_code == 201
    assert r.headers["content-type"] == "application/json"
    assert list(r.json().keys()) == ["tid"]
    assert isinstance(UUID(tid), UUID)

    r = requests.get(BASE + f"task/{tid}/")
    collection = r.json().get("collection")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert isinstance(UUID(collection), UUID)
    
    r = requests.get(BASE + f"task/{tid}/")
    while r.json().get("status") != 2:
        r = requests.get(BASE + f"task/{tid}/")
    assert r.status_code == 200
    assert r.json().get("input") == r.json().get("finished")

    r = requests.delete(BASE + f"task/{tid}/")
    assert r.status_code == 200


def test_face_outputs_alt():
    r = requests.get(BASE + f"scan/logs/{COLLECTION_2}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert r.json().get("samples") == 10

    r = requests.get(BASE + f"scan/{COLLECTION_2}/profiles")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 10


def test_finger_scan_default(tmp_path):
    """
    GIVEN a set of mock fingerprint images
    WHEN the images processed by the default engine
    THEN check if the output values are properly generated
    """
    samples = "tests/samples/finger.zip"
    with ZipFile(samples, "r") as z:
        input_dir = tmp_path / "input"
        input_dir = str(input_dir) + "/"
        z.extractall(input_dir)

    payload = {
        "options": {
            "engine": "default"
        },
        "input": input_dir,
        "collection": COLLECTION_3
    }
    r = requests.post(BASE + "scan/?modality=fingerprint", json=payload)
    tid = r.json().get("tid")
    assert r.status_code == 201
    assert r.headers["content-type"] == "application/json"
    assert list(r.json().keys()) == ["tid"]
    assert isinstance(UUID(tid), UUID)

    r = requests.get(BASE + f"task/{tid}/")
    collection = r.json().get("collection")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert isinstance(UUID(collection), UUID)
    
    r = requests.get(BASE + f"task/{tid}/")
    while r.json().get("status") != 2:
        r = requests.get(BASE + f"task/{tid}/")
    assert r.status_code == 200
    assert r.json().get("input") == r.json().get("finished")

    r = requests.delete(BASE + f"task/{tid}/")
    assert r.status_code == 200


def test_finger_outputs_default():
    r = requests.get(BASE + f"scan/logs/{COLLECTION_3}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert r.json().get("samples") == 5

    r = requests.get(BASE + f"scan/{COLLECTION_3}/profiles")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 5


def test_iris_scan_default(tmp_path):
    """
    GIVEN a set of mock iris images
    WHEN the images processed by the default engine
    THEN check if the output values are properly generated
    """
    samples = "tests/samples/iris.zip"
    with ZipFile(samples, "r") as z:
        input_dir = tmp_path / "input"
        input_dir = str(input_dir) + "/"
        z.extractall(input_dir)

    payload = {
        "options": {
            "engine": "default"
        },
        "input": input_dir,
        "collection": COLLECTION_4
    }
    r = requests.post(BASE + "scan/?modality=iris", json=payload)
    tid = r.json().get("tid")
    assert r.status_code == 201
    assert r.headers["content-type"] == "application/json"
    assert list(r.json().keys()) == ["tid"]
    assert isinstance(UUID(tid), UUID)

    r = requests.get(BASE + f"task/{tid}/")
    collection = r.json().get("collection")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert isinstance(UUID(collection), UUID)
    
    r = requests.get(BASE + f"task/{tid}/")
    while r.json().get("status") != 2:
        r = requests.get(BASE + f"task/{tid}/")
    assert r.status_code == 200
    assert r.json().get("input") == r.json().get("finished")

    r = requests.delete(BASE + f"task/{tid}/")
    assert r.status_code == 200


def test_iris_outputs_default():
    r = requests.get(BASE + f"scan/logs/{COLLECTION_4}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert r.json().get("samples") == 5

    r = requests.get(BASE + f"scan/{COLLECTION_4}/profiles")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 5


def test_report():
    r = requests.post(BASE + f"scan/{COLLECTION_3}/report/generate")
    assert r.status_code == 202

    r = requests.get(BASE + f"scan/{COLLECTION_3}/report")
    while r.status_code != 200:
        r = requests.get(BASE + f"scan/{COLLECTION_3}/report")
    assert r.headers["content-type"] == "text/html; charset=utf-8"


def test_clean_up():
    r = requests.delete(BASE + f"scan/logs/{COLLECTION_1}")
    assert r.status_code == 200

    r = requests.delete(BASE + f"scan/{COLLECTION_1}/profiles")
    assert r.status_code == 200

    r = requests.delete(BASE + f"scan/logs/{COLLECTION_2}")
    assert r.status_code == 200

    r = requests.delete(BASE + f"scan/{COLLECTION_2}/profiles")
    assert r.status_code == 200

    r = requests.delete(BASE + f"scan/logs/{COLLECTION_3}")
    assert r.status_code == 200

    r = requests.delete(BASE + f"scan/{COLLECTION_3}/profiles")
    assert r.status_code == 200

    r = requests.delete(BASE + f"scan/logs/{COLLECTION_4}")
    assert r.status_code == 200

    r = requests.delete(BASE + f"scan/{COLLECTION_4}/profiles")
    assert r.status_code == 200

    r = requests.delete(BASE + f"scan/{COLLECTION_3}/report")
    assert r.status_code == 200


def test_engine_info():
    """
    GIVEN the server running
    WHEN the endpoint was accessed
    THEN check if the response is valid
    """
    r = requests.get(BASE + "scan/info")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert list(r.json().keys()) == ["backend", "version"]

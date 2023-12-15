# Biometric Quality Assessment Tool (BQAT)

BQAT is a biometric quality assessment tool for generating and analysing biometric sample quality to international standards and supporting customized metrics. It takes as input directory of biometric images/data in standard formats (e.g. wsq,png,jpg) and output both the raw quality information as well as an analysis report.

## bqat-api
This project run as a server which provides BQAT functionalities as Restful API.

## Getting started
``` sh
# build docker image
docker compose build

# run local container with log from the API
docker compose up -d

# stop the service (ctrl + C)
docker compose down
```

## Usage
The documentation of the endpoints lives in:
* `localhost:8848/docs`

In dev mode, there is an management frontend for the database:
* `localhost:8081/`

## Test and Deploy
__TODO__

## Authors and acknowledgment
__TODO__

## License
__TODO__

## Project status
__TODO__

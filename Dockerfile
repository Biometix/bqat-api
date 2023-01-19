# syntax=docker/dockerfile:1

FROM mitre/biqt:latest

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=off
ENV MPLCONFIGDIR=/app/temp
# ENV RAY_USE_MULTIPROCESSING_CPU_COUNT=1
ENV RAY_DISABLE_DOCKER_CPU_WARNING=1


RUN yum -y update && \
    yum -y install epel-release && \
    yum -y groupinstall "Development Tools" && \
    yum -y install openssl-devel bzip2-devel libffi-devel xz-devel && \
    yum -y install wget

# RUN mkdir -p /root/.deepface/weights

# RUN wget https://github.com/serengil/deepface_models/releases/download/v1.0/facial_expression_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/age_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/gender_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/race_model_single_batch.h5 -P /root/.deepface/weights/

# COPY bqat/core/bqat_core/misc/nfiq2-2.2.0-1.el7.x86_64.rpm /app/misc/
RUN wget https://github.com/usnistgov/NFIQ2/releases/download/v2.2.0/nfiq2-2.2.0-1.el7.x86_64.rpm -P /app/misc/ && \
    yum -y install ./misc/*el7*rpm

COPY bqat/bqat_core/misc/haarcascade_smile.xml bqat_core/misc/haarcascade_smile.xml

RUN wget https://www.python.org/ftp/python/3.8.16/Python-3.8.16.tgz && \
    tar xvf Python-3.8.16.tgz && cd Python-3.8*/ && \
    ./configure --enable-optimizations && \
    make altinstall

COPY Pipfile Pipfile.lock /app/

RUN python3.8 -m pip install --upgrade pip && \
    python3.8 -m pip install pipenv && \
    pipenv requirements > requirements.txt && \
    python3.8 -m pip install -r requirements.txt

COPY . .

ARG Version
LABEL BQAT.Version=$Version

RUN useradd assessor
RUN chown -R assessor /app
USER assessor

ENTRYPOINT [ "/bin/bash", "-l", "-c" ]
CMD [ "python3.8 -m api" ]

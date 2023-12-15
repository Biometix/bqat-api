FROM ubuntu:22.04 AS build

SHELL ["/bin/bash", "-c"] 

## BIQT ##
ARG QUIRK_STRIP_QT5CORE_METADATA=ON
ENV QUIRK_STRIP_QT5CORE_METADATA ${QUIRK_STRIP_QT5CORE_METADATA}

ARG WITH_BIQT_FACE=ON
ENV WITH_BIQT_FACE ${WITH_BIQT_FACE}

ARG WITH_BIQT_IRIS=ON
ENV WITH_BIQT_IRIS ${WITH_BIQT_IRIS}

ARG WITH_BIQT_CONTACT_DETECTOR=ON
ENV WITH_BIQT_CONTACT_DETECTOR ${WITH_BIQT_CONTACT_DETECTOR}

RUN set -e && \
    apt update && \
    apt upgrade -y; \
    DEBIAN_FRONTEND=noninteractive apt -y install git less vim cmake g++ curl libopencv-dev libjsoncpp-dev pip && \
    pip install wheel; \
    if [[ "${WITH_BIQT_FACE}" == "ON" ]]; then \
    set -e; \
    echo "Installing QT5 for BIQT Face."; \
    DEBIAN_FRONTEND=noninteractive apt -y install qtbase5-dev; \
    if  [ "${QUIRK_STRIP_QT5CORE_METADATA}" == "ON" ]; then \
    echo "Stripping libQt5Core.so of its ABI metadata."; \
    strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so; \
    fi; \
    fi;

ARG BIQT_COMMIT=master
ENV BIQT_COMMIT ${BIQT_COMMIT}

# Clone and install BIQT from MITRE Github.
RUN set -e; \
    echo "BIQT_COMMIT=${BIQT_COMMIT}" ; \
    mkdir /app 2>/dev/null || true; \
    cd /app; \
    git clone --verbose https://github.com/mitre/biqt --branch "${BIQT_COMMIT}" biqt-pub; \
    export NUM_CORES=$(cat /proc/cpuinfo | grep -Pc "processor\s*:\s*[0-9]+\s*$"); \
    echo "Builds will use ${NUM_CORES} core(s)."; \
    cd /app/biqt-pub; \
    mkdir build; \
    cd build; \
    cmake -DBUILD_TARGET=UBUNTU -DCMAKE_BUILD_TYPE=Release -DWITH_JAVA=OFF ..; \
    make -j${NUM_CORES}; \
    make install; \
    source /etc/profile.d/biqt.sh

ARG BIQT_IRIS_COMMIT=master
ENV BIQT_IRIS_COMMIT ${BIQT_IRIS_COMMIT}

# Stage 2: BIQT Iris
COPY bqat/bqat_core/misc/BIQT-IRIS /app/biqt-iris/

# RUN if [ "${WITH_BIQT_IRIS}" == "ON" ]; then \
RUN source /etc/profile.d/biqt.sh; \
    export NUM_CORES=$(cat /proc/cpuinfo | grep -Pc "processor\s*:\s*[0-9]+\s*$"); \
    echo "Builds will use ${NUM_CORES} core(s)."; \
    cd /app/biqt-iris; \
    mkdir build; \
    cd build; \
    cmake -DBIQT_HOME=/usr/local/share/biqt -DCMAKE_BUILD_TYPE=Release ..; \
    make -j${NUM_CORES}; \
    make install;
    # else \
    # echo "Skipping BIQT Iris."; \
    # fi;

# RUN set -e; \
#     if [ "${WITH_BIQT_IRIS}" == "ON" ]; then \
#     echo "BIQT_IRIS_COMMIT: ${BIQT_IRIS_COMMIT}"; \
#     source /etc/profile.d/biqt.sh; \
#     ( mkdir /app 2>/dev/null || true ); \
#     cd /app; \
#     git clone --verbose https://github.com/mitre/biqt-iris --branch "${BIQT_IRIS_COMMIT}" biqt-iris; \
#     export NUM_CORES=$(cat /proc/cpuinfo | grep -Pc "processor\s*:\s*[0-9]+\s*$"); \
#     echo "Builds will use ${NUM_CORES} core(s)."; \
#     cd /app/biqt-iris; \
#     mkdir build; \
#     cd build; \
#     cmake -DCMAKE_BUILD_TYPE=Release ..; \
#     make -j${NUM_CORES}; \
#     make install; \
#     else \
#     echo "Skipping BIQT Iris."; \
#     fi;


# Clone and install OpenBR from GitHub. 
RUN set -e; \
    if [ "${WITH_BIQT_FACE}" == "ON" ]; then \
    echo "Using OpenSSL Configuration at ${OPENSSL_CONF}: `cat ${OPENSSL_CONF}`"; \
    mkdir /app 2>/dev/null || true; \
    cd /app; \
    git clone https://github.com/biometrics/openbr.git openbr || exit 5; \
    cd /app/openbr; \
    git checkout 1e1c8f; \
    mkdir build; \
    cd build; \
    cmake -DCMAKE_BUILD_TYPE=Release -DBR_WITH_OPENCV_NONFREE=OFF -DCMAKE_INSTALL_PREFIX=/opt/openbr ..; \
    export NUM_CORES=$(cat /proc/cpuinfo | grep -Pc "processor\s*:\s*[0-9]+\s*$"); \
    make -j${NUM_CORES}; \
    make install; \
    else \
    echo "Skipping OpenBR build for BIQT Face. BIQT Face not requested."; \
    mkdir /opt/openbr || true; \
    echo "WITH_BIQT_FACE was not set to ON so openbr not compiled and installed." > /opt/openbr/README; \
    fi

ARG BIQT_FACE_COMMIT=master
ENV BIQT_FACE_COMMIT ${BIQT_FACE_COMMIT}
# Clone and install BIQT Face from the MITRE github repository. 
RUN set -e; \
    source /etc/profile.d/biqt.sh; \
    if [ "${WITH_BIQT_FACE}" == "ON" ]; then \
    echo "BIQT_FACE_COMMIT: ${BIQT_FACE_COMMIT}"; \        
    echo "Using OpenSSL Configuration at ${OPENSSL_CONF}: `cat ${OPENSSL_CONF}`"; \
    mkdir /app 2>/dev/null || true; \
    cd /app; \
    git clone https://github.com/mitre/biqt-face.git biqt-face --depth=1 --branch "${BIQT_FACE_COMMIT}"; \
    cd /app/biqt-face; \
    mkdir build; \
    cd build; \
    cmake -DCMAKE_BUILD_TYPE=Release -DOPENBR_DIR=/opt/openbr ..; \
    make -j${NUM_CORES}; \
    make install; \
    else \
    echo "Skipping BIQT Face."; \
    fi;


# ARG BIQT_CONTACT_DETECTOR_COMMIT=master
# ENV BIQT_CONTACT_DETECTOR_COMMIT ${BIQT_CONTACT_DETECTOR_COMMIT}
# # Stage 3: BIQT Contact Detector
# RUN set -e; \
#     source /etc/profile.d/biqt.sh; \
#     if [ "${WITH_BIQT_CONTACT_DETECTOR}" == "ON" ]; then \
#     ( mkdir /app 2>/dev/null || true ); \
#     cd /app; \
#     git clone https://github.com/mitre/biqt-contact-detector biqt-contact-detector --branch "${BIQT_CONTACT_DETECTOR_COMMIT}" --depth 1; \
#     cd biqt-contact-detector; \
#     pip install -r requirements.txt; \
#     export NUM_CORES=$(cat /proc/cpuinfo | grep -Pc "processor\s*:\s*[0-9]+\s*$"); \
#     mkdir build; \
#     cd build; \
#     cmake -DCMAKE_BUILD_TYPE=Release ..; \
#     make -j${NUM_CORES}; \
#     make install; \
#     fi;


RUN apt update && apt -y install cmake build-essential libssl-dev libdb-dev libdb++-dev libopenjp2-7 libopenjp2-tools libpcsclite-dev libssl-dev libopenjp2-7-dev libjpeg-dev libpng-dev libtiff-dev zlib1g-dev libopenmpi-dev libdb++-dev libsqlite3-dev libhwloc-dev libavcodec-dev libavformat-dev libswscale-dev; \
    ( mkdir /app 2>/dev/null || true ); \
    cd /app; \
    git clone --recursive https://github.com/usnistgov/NFIQ2.git; \
    cd NFIQ2; \
    mkdir build; \
    cd build; \
    cmake .. -DCMAKE_CONFIGURATION_TYPES=Release; \
    cmake --build . --config Release; \
    cmake --install .


FROM ubuntu:22.04 AS release

# SHELL ["/bin/bash", "-c"]

RUN apt update && \
    apt -y install curl g++ libopencv-core4.5d libopencv-highgui4.5d libopencv-imgcodecs4.5d libopencv-imgproc4.5d libjsoncpp25 libqt5xml5 libqt5sql5  libpython3.10 libopencv-objdetect4.5d libqt5widgets5 libopencv-ml4.5d libopencv-videoio4.5d libpython3.10-dev python3-distutils
    # apt -y install sqlite-devel openssl-devel bzip2-devel libffi-devel xz-devel

## BIQT ##
COPY --from=build /usr/local /usr/local
COPY --from=build /etc/profile.d/biqt.sh /etc/profile.d/biqt.sh
COPY --from=build /opt/openbr /opt/openbr

RUN if  [ "${QUIRK_STRIP_QT5CORE_METADATA}" == "ON" ]; then \
    echo "Stripping libQt5Core.so of its ABI metadata."; \
    strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so; \
    fi;


## NFIQ2 ##
WORKDIR /app

COPY --from=build /usr/lib /usr/lib

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=off
ENV MPLCONFIGDIR=/app/temp
# ENV RAY_USE_MULTIPROCESSING_CPU_COUNT=1
ENV RAY_DISABLE_DOCKER_CPU_WARNING=1

COPY bqat/bqat_core/misc/haarcascade_smile.xml bqat_core/misc/haarcascade_smile.xml

COPY bqat/bqat_core/misc/NISQA/conda-lock.yml .

COPY bqat/bqat_core/misc/NISQA /app/

RUN curl -L -O "https://github.com/conda-forge/miniforge/releases/download/23.1.0-4/Mambaforge-$(uname)-$(uname -m).sh" && \
    ( echo yes ; echo yes ; echo mamba ; echo yes ) | bash Mambaforge-$(uname)-$(uname -m).sh
ENV PATH=/app/mamba/bin:${PATH}
RUN mamba install --channel=conda-forge --name=base conda-lock=1.4 && \
    conda-lock install --name nisqa conda-lock.yml && \
    mamba clean -afy

COPY Pipfile /app/

RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install pipenv && \
    pipenv lock --dev && \
    pipenv requirements --dev > requirements.txt && \
    python3 -m pip install -r requirements.txt

# RUN mkdir -p /root/.deepface/weights && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/facial_expression_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/age_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/gender_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/race_model_single_batch.h5 -P /root/.deepface/weights/

# RUN useradd assessor
# RUN chown -R assessor /app
# USER assessor

RUN mkdir data

COPY bqat bqat/
COPY api api/

ARG VER_CORE
ARG VER_API
LABEL BQAT.core.version=$VER_CORE
LABEL BQAT.api.version=$VER_API

ENTRYPOINT [ "/bin/bash", "-l", "-c" ]
CMD [ "python3 -m api" ]

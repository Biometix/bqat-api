FROM ubuntu:jammy AS build

SHELL ["/bin/bash", "-c"]

WORKDIR /app

# COPY bqat/core/bqat_core/misc/BIQT-Iris /app/biqt-iris/

RUN set -e && \
    apt update && \
    apt upgrade -y; \
    DEBIAN_FRONTEND=noninteractive apt -y install git less vim g++ curl libopencv-dev libjsoncpp-dev qtbase5-dev && \
    apt -y install build-essential libssl-dev libdb-dev libdb++-dev libopenjp2-7 libopenjp2-tools libpcsclite-dev libssl-dev libopenjp2-7-dev libjpeg-dev libpng-dev libtiff-dev zlib1g-dev libopenmpi-dev libdb++-dev libsqlite3-dev libhwloc-dev libavcodec-dev libavformat-dev libswscale-dev; \
    strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so; \
    curl -L -O https://github.com/Kitware/CMake/releases/download/v3.29.1/cmake-3.29.1-linux-x86_64.sh; \
    chmod +x cmake*.sh; mkdir /opt/cmake; ./cmake*.sh --prefix=/opt/cmake --skip-license; ln -s /opt/cmake/bin/cmake /usr/local/bin/cmake;\
    mkdir /app 2>/dev/null || true; \
    cd /app; \
    git clone --verbose https://github.com/mitre/biqt --branch master biqt-pub; \
    export NUM_CORES=$(cat /proc/cpuinfo | grep -Pc "processor\s*:\s*[0-9]+\s*$"); \
    echo "Builds will use ${NUM_CORES} core(s)."; \
    cd /app/biqt-pub; \
    mkdir build; \
    cd build; \
    cmake -DBUILD_TARGET=UBUNTU -DCMAKE_BUILD_TYPE=Release -DWITH_JAVA=OFF ..; \
    make -j${NUM_CORES}; \
    make install; \
    source /etc/profile.d/biqt.sh; \
    cd /app; git clone https://github.com/mitre/biqt-iris.git; \
    cd /app/biqt-iris; \
    mkdir build; \
    cd build; \
    cmake -DBIQT_HOME=/usr/local/share/biqt -DCMAKE_BUILD_TYPE=Release ..; \
    make -j${NUM_CORES}; \
    make install; \
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
    cd /app; \
    git clone https://github.com/mitre/biqt-face.git biqt-face --depth=1 --branch master; \
    cd /app/biqt-face; \
    mkdir build; \
    cd build; \
    cmake -DCMAKE_BUILD_TYPE=Release -DOPENBR_DIR=/opt/openbr ..; \
    make -j${NUM_CORES}; \
    make install; \
    cd /app; \
    git clone --recursive https://github.com/usnistgov/NFIQ2.git; \
    cd NFIQ2; \
    git checkout 2a899239d3d72f302cad859145745e8703e32ab0; \
    mkdir build; \
    cd build; \
    cmake .. -DCMAKE_CONFIGURATION_TYPES=Release; \
    cmake --build . --config Release; \
    cmake --install .

RUN apt install -y python3-pip liblapack-dev; \
    pip install conan cmake; \
    cd /app; mkdir ofiq; cd ofiq; \
    git clone https://github.com/BSI-OFIQ/OFIQ-Project.git; \
    cd OFIQ-Project/scripts; \
    chmod +x *.sh; \
    ./build.sh

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


FROM ubuntu:jammy AS release

WORKDIR /app

COPY --from=build /usr/local /usr/local
COPY --from=build /etc/profile.d/biqt.sh /etc/profile.d/biqt.sh
COPY --from=build /opt/openbr /opt/openbr

COPY --from=build /usr/lib /usr/lib

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=off
ENV MPLCONFIGDIR=/app/temp
# ENV RAY_USE_MULTIPROCESSING_CPU_COUNT=1
ENV RAY_DISABLE_DOCKER_CPU_WARNING=1
ENV YDATA_PROFILING_NO_ANALYTICS=True
# ENV YOLO_CONFIG_DIR=/tmp/yolo

COPY bqat/bqat_core/misc/BQAT /app/BQAT/
COPY bqat/bqat_core/misc/NISQA /app/NISQA/
COPY bqat/bqat_core/misc/OFIQ /app/OFIQ/
COPY Pipfile /app/

COPY tests /app/tests/

RUN apt update && apt -y install curl ca-certificates libblas-dev liblapack-dev python3-pip libsndfile1; \
    python3 -m pip install pipenv && \
    pipenv lock; \
    pipenv requirements > requirements.txt; \
    if [ "${DEV}" == "true" ]; \
    then pipenv requirements --dev > requirements.txt; \
    else pipenv requirements > requirements.txt; \
    fi; \
    python3 -m pip uninstall -y pipenv && \
    python3 -m pip install -r requirements.txt

# RUN mkdir -p /root/.deepface/weights && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/facial_expression_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/age_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/gender_model_weights.h5 -P /root/.deepface/weights/ && \
#     wget https://github.com/serengil/deepface_models/releases/download/v1.0/race_model_single_batch.h5 -P /root/.deepface/weights/

RUN mkdir data

COPY bqat bqat/
COPY api api/
COPY api/favicon.png .

COPY --from=build /app/ofiq/OFIQ-Project/install_x86_64_linux/Release/bin ./OFIQ/bin
COPY --from=build /app/ofiq/OFIQ-Project/install_x86_64_linux/Release/lib ./OFIQ/lib
COPY --from=build /app/ofiq/OFIQ-Project/data/models ./OFIQ/models

ARG VER_CORE
ARG VER_API
LABEL BQAT.core.version=$VER_CORE
LABEL BQAT.api.version=$VER_API

HEALTHCHECK --interval=5m --timeout=5m CMD curl --fail -s http://localhost:8848/info || sleep 30 && curl --fail -s http://localhost:8848/info || sleep 30 && curl --fail -s http://localhost:8848/info || kill -9 1

# RUN groupadd -r appgroup && useradd -r -g appgroup assessor && chown -R assessor /app && chown -R assessor /usr/local
# USER assessor

ENTRYPOINT [ "/bin/bash", "-l", "-c" ]
CMD [ "python3 -m api" ]

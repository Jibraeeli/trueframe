# Converts the model to ONNX. Nothing from this stage ships except that file.
# ONNX files work on any CPU, so this runs natively even when building for ARM.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS model
RUN pip install --no-cache-dir torch==2.8.0 torchvision==0.23.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir timm==1.0.19 safetensors==0.8.0 onnx==1.23.2 \
        onnxruntime==1.31.1 numpy==2.5.4
COPY app/worker/export_model.py /tmp/export_model.py
RUN python /tmp/export_model.py /models/detector.onnx


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODEL_PATH=/models/detector.onnx
WORKDIR /srv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY app/worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY --from=model /models /models

COPY app/__init__.py app/__init__.py
COPY app/shared app/shared
COPY app/worker app/worker

RUN useradd --create-home --uid 10001 trueframe
USER trueframe

CMD ["python", "-m", "app.worker.main"]


# Adds the API and the test tools, so tests can run the whole flow.
FROM runtime AS test
USER root
COPY app/api/requirements.txt /tmp/api-requirements.txt
COPY tests/requirements.txt /tmp/test-requirements.txt
RUN pip install --no-cache-dir -r /tmp/api-requirements.txt -r /tmp/test-requirements.txt
COPY app/api app/api
COPY app/web app/web
COPY tests tests
USER trueframe
CMD ["pytest", "-q", "-p", "no:cacheprovider", "tests"]

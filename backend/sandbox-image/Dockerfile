# Image used by DockerSandbox to run untrusted target code. Contains no secrets.
FROM python:3.12-slim
COPY extra-requirements.txt /tmp/extra-requirements.txt
RUN pip install --no-cache-dir pytest hypothesis \
    && pip install --no-cache-dir -r /tmp/extra-requirements.txt \
    && rm /tmp/extra-requirements.txt
USER 65534:65534

# Image used by DockerSandbox to run untrusted target code. Contains no secrets.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest hypothesis
USER 65534:65534

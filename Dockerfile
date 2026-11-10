# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM debian:trixie-slim AS model
ADD --checksum=sha256:5a2cb0188a3f392f88c5d226768abd0da7b2b6a5abdbb50abedcd7c8f42d9fb1 https://github.com/ggml-org/llama.cpp/releases/download/b12250/llama-b12250-bin-ubuntu-x64.tar.gz /tmp/llama.tar.gz
RUN mkdir /llama && tar -xzf /tmp/llama.tar.gz -C /llama --strip-components=1
ADD --checksum=sha256:74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf /model.gguf
ADD --checksum=sha256:2a31195d3769c0b0fd0a4906201666108834848db768af11de1d2cef7cd35e65 https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF/resolve/b9e4379657e1450d04d02eec8e345667265b0a00/SmolVLM-256M-Instruct-Q8_0.gguf /vision.gguf
ADD --checksum=sha256:7e943f7c53f0382a6fc41b6ee0c2def63ba4fded9ab8ed039cc9e2ab905e0edd https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF/resolve/b9e4379657e1450d04d02eec8e345667265b0a00/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf /vision-mmproj.gguf

FROM python:3.11-slim-trixie
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libcurl4t64 && rm -rf /var/lib/apt/lists/*
COPY --from=model /llama /opt/llama
COPY --from=model /model.gguf /opt/model.gguf
COPY --from=model /vision.gguf /vision-mmproj.gguf /opt/
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY backend/data/demo-v1.json backend/data/demo-v1.json
COPY --from=web /app/frontend/dist frontend/dist
ENV COYOTE_DB_PATH=/data/coyote.sqlite3
ENV COYOTE_LLM_URL=http://127.0.0.1:8081
ENV COYOTE_VISION_URL=http://127.0.0.1:8082
ENV LD_LIBRARY_PATH=/opt/llama
EXPOSE 8090
CMD ["sh", "-c", "/opt/llama/llama-server -m /opt/model.gguf --alias Qwen2.5-0.5B-Instruct --host 127.0.0.1 --port 8081 -c 1536 -np 1 -t 2 -b 128 -ub 128 & /opt/llama/llama-server -m /opt/vision.gguf --mmproj /opt/vision-mmproj.gguf --alias SmolVLM-256M-Instruct --host 127.0.0.1 --port 8082 -c 1536 -np 1 -t 2 -b 128 -ub 128 & exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8090}"]

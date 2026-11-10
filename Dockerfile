FROM node:24-bookworm-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY backend/data/demo-v1.json backend/data/demo-v1.json
COPY --from=web /app/frontend/dist frontend/dist
ENV COYOTE_DB_PATH=/data/coyote.sqlite3
EXPOSE 8090
CMD ["sh", "-c", "exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8090}"]

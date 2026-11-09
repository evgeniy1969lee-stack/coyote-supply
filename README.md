# Coyote Supply

Хакатон Global Coffee × Coyote, кейс 04 — прототип прогноза закупок для кофейни.

## Начало работы

План MVP, архитектура, критерии и распределение ролей находятся в [docs/mvp-plan.md](docs/mvp-plan.md). Перед реализацией уточните у Coyote, какие функции прогнозирования уже доступны и какие тестовые данные можно использовать.

Демо запускается по [инструкции для фронтенда](frontend/README.md). Для демонстрации используйте синтетические данные, а реальные данные и ключи доступа храните вне репозитория.

[Задачи для бэкенда и прогнозирования](docs/backend-ml-tasks.md) описывают порядок разработки, контрольные сценарии и критерии приёмки.

## Backend на Windows

Команды выполняются из корня репозитория. Требуется Python 3.11 или новее.

```powershell
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
& .\.venv\Scripts\python.exe -m pytest backend/tests -q
& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Swagger UI доступен по адресу [localhost:8000/docs](http://127.0.0.1:8000/docs).
По умолчанию SQLite создаётся в `backend/data/drafts.sqlite3`. Чтобы использовать
другой файл, задайте `$env:COYOTE_DB_PATH = 'C:\путь\drafts.sqlite3'` перед запуском.

При наличии `frontend/dist/index.html` FastAPI также раздаёт сборку по корневому адресу.
Текущий frontend использует свои фикстуры и браузерное хранилище. Для подключения
к сервису используйте [контракт и примеры ответов](docs/api-contract.md).

Расчёт опирается на [синтетический набор](backend/data/demo-v1.json) с фиксированной
датой 9 ноября 2026 года. [Сценарий демонстрации и проверка модели](docs/demo.md).

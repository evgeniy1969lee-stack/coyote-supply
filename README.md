# Coyote OS

Хакатон Global Coffee × Coyote, кейс №4. Панель смены связывает склад, прогноз расхода, закупки и помощника бариста. В демо списание пересчитывает прогноз на сервере, а черновик сохраняется в SQLite.

## Локальный запуск

Команды выполняются из корня репозитория в PowerShell. Проверено с Python 3.11 и Node.js 24.

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
$env:COYOTE_DB_PATH = Join-Path (Get-Location).Path 'backend/data/coyote-os-demo.sqlite3'
& .venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8090
```

FastAPI раздаёт интерфейс и API с одного адреса. Сохранения и потери сохраняются при перезапуске с тем же SQLite-файлом. Для чистого демо задайте новый путь через `COYOTE_DB_PATH`. [Открыть Coyote OS](http://127.0.0.1:8090/) · [Swagger](http://127.0.0.1:8090/docs)

## Проверка

```powershell
& .venv/Scripts/python.exe -m pytest backend/tests -q
npm --prefix frontend run lint
npm --prefix frontend run build
```

Пошаговый сценарий защиты, устройство новой смены и проверка браузера описаны отдельно. [Сценарий Coyote OS](docs/coyote-os.md) · [Контракт закупок](docs/api-contract.md) · [Работа над фронтендом](frontend/README.md)

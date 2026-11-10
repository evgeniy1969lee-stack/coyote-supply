# Coyote

**Команда Cheremsha · Хакатон Global Coffee × Coyote · Кейс №4**

Coyote помогает управляющему кофейней понять, каких ингредиентов не хватит до поставки и сколько заказать на период после неё. Сервер рассчитывает расход из продаж и техкарт, учитывает остатки, партии, график поставок и размер упаковки. После списания он пересчитывает рекомендации, а управляющий сверяет и сохраняет черновик закупки. Copilot объясняет расчёт по данным выбранной точки.

**Стек** — React, TypeScript и Vite для интерфейса, FastAPI и SQLite для API и хранения. Один сервер раздаёт сайт и API.

**Copilot** — Qwen2.5-0.5B-Instruct (Q4_K_M), запущенная через llama.cpp на CPU внутри контейнера. Модель помогает распознать свободную формулировку и пишет короткое пояснение. Сервер показывает остатки, объёмы закупки и техкарты отдельно. Имя модели отображается, когда она участвовала в ответе. Если она недоступна, работает прямой поиск по поддерживаемым вопросам. [Модель Qwen](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF)

## Локальный запуск

Команды выполняются из корня репозитория в PowerShell. Проверено с Python 3.11 и Node.js 24.

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
$env:COYOTE_DB_PATH = Join-Path (Get-Location).Path 'backend/data/coyote.sqlite3'
& .venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8090
```

Списания и черновики сохраняются при перезапуске с тем же файлом SQLite. Для чистой репетиции остановите сервер, выполните команду ниже и снова запустите Uvicorn. Каждый вызов создаёт путь к отдельной базе.

```powershell
$env:COYOTE_DB_PATH = Join-Path ([IO.Path]::GetTempPath()) "coyote-rehearsal-$([guid]::NewGuid()).sqlite3"
```

[Открыть Coyote](http://127.0.0.1:8090/) · [Swagger](http://127.0.0.1:8090/docs)

Для локальной проверки именно LLM используйте контейнер ниже или запустите llama.cpp отдельно и задайте `COYOTE_LLM_URL`, например `http://127.0.0.1:8081`.

## Проверка

```powershell
& .venv/Scripts/python.exe -m pytest backend/tests -q
npm --prefix frontend run lint
npm --prefix frontend run build
& .venv/Scripts/python.exe -m backend.app.backtest
```

Backtest сравнивает медиану по дням недели, значение прошлой недели и среднее за предыдущие семь дней на общих отложенных наблюдениях. [Результаты backtest](docs/demo.md) · [Сценарий защиты и проверка в браузере](docs/coyote-os.md) · [Контракт API](docs/api-contract.md) · [Работа над фронтендом](frontend/README.md)

## Развёртывание на Railway

1. В Railway подключите GitHub-репозиторий и выберите ветку с этим README. Оставьте корень репозитория как корень сервиса. Railway соберёт многостадийный `Dockerfile`.
2. Подключите постоянный Volume с путём `/data`. Приложение использует `COYOTE_DB_PATH=/data/coyote.sqlite3` и слушает порт из `PORT`. Для SQLite оставьте одну реплику.
3. Укажите `/api/health` как Healthcheck Path и сгенерируйте HTTPS-домен в Public Networking. Откройте домен, выполните сценарий и после перезапуска сервиса проверьте сохранённый черновик.

Для локальной проверки контейнера с Docker выполните из корня репозитория:

```powershell
docker build -t cheremsha-coyote .
docker run --rm -p 8091:8090 -v coyote-data:/data cheremsha-coyote
```

Публичный экземпляр предназначен для синтетического набора. Черновики и списания общие для посетителей одной точки. Для рабочих данных нужен закрытый экземпляр с контролем доступа.

[Dockerfile в Railway](https://docs.railway.com/builds/dockerfiles) · [Постоянные тома Railway](https://docs.railway.com/volumes)

## Подключение данных Global Coffee и Coyote

По умолчанию приложение использует синтетические продажи, остатки и техкарты. Для проверки согласованной обезличенной выгрузки преобразуйте её в JSON по модели `Dataset` из [backend/app/data.py](backend/app/data.py) и задайте `COYOTE_DATASET_PATH` как абсолютный путь. Снимок должен включать точку и часовой пояс, закрытые дни продаж, строки продаж, версии техкарт, остатки и партии, поставки, упаковки и цены. При импорте сопоставьте SKU и идентификаторы ингредиентов с каталогом. Для готовых вопросов Copilot используйте идентификаторы из [справочника Copilot](backend/app/copilot.py).

Сервер проверяет структуру и ссылки при запуске. Backtest использует ту же переменную и читает тот же снимок. Реальный формат выгрузки и качество прогноза нужно подтвердить на данных, согласованных с Global Coffee и Coyote. Для каждого независимого набора используйте отдельный SQLite-файл.

```powershell
$env:COYOTE_DATASET_PATH = 'C:\path\to\snapshot.json'
$env:COYOTE_DB_PATH = Join-Path ([IO.Path]::GetTempPath()) "coyote-import-$([guid]::NewGuid()).sqlite3"
& .venv/Scripts/python.exe -m backend.app.backtest
& .venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8090
```

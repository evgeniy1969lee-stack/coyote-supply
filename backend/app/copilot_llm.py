"""Use Qwen to interpret questions and explain grounded answers."""

import json
import logging
import os
import re
from threading import BoundedSemaphore
from urllib.request import Request, urlopen

from .copilot import DRINKS, INGREDIENTS, CopilotAnswer, answer_question
from .data import Dataset
from .shift import ShiftOverview

MODEL = "Qwen2.5-0.5B-Instruct"
_slot = BoundedSemaphore(1)
_logger = logging.getLogger(__name__)
_MODEL_ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError)


def complete(endpoint: str, body: dict) -> str:
    request = Request(
        f"{endpoint.rstrip('/')}/v1/chat/completions",
        data=json.dumps({"model": MODEL, **body}, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=12) as response:
        return json.load(response)["choices"][0]["message"]["content"]


def select_route(endpoint: str, menu: str, question: str, routes: list[str]) -> str:
    schema = {
        "type": "object",
        "properties": {"route": {"type": "string", "enum": routes}},
        "required": ["route"],
        "additionalProperties": False,
    }
    body = {
        "temperature": 0,
        "max_tokens": 48,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Classify the Russian cafe question. Output a single allowed route.\n"
                    "stock = current amount (сколько осталось).\n"
                    "purchase = quantity to buy (сколько заказать, объём у поставщика).\n"
                    "shortage = will supplies last until delivery (хватит ли до прихода).\n"
                    "recipe = drink ingredients (из чего готовят). loss = effect of write-off.\n"
                    "shift = first task. none = unrelated or unclear.\n"
                    f"Allowed routes and subjects: {menu}"
                ),
            },
            {"role": "user", "content": question},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "route", "schema": schema}},
    }
    return json.loads(complete(endpoint, body))["route"]


def explain(endpoint: str, question: str, answer: CopilotAnswer) -> CopilotAnswer:
    facts = re.sub(r"\d+(?:[,.]\d+)?\s*(?:мл|кг|л|г|уп\.|шт\.|₸)(?!\w)", "указанный объём", answer.answer)
    facts = re.sub(r"\d+(?:[.,:]\d+)*", "по расчёту", facts)
    try:
        note = complete(endpoint, {
            "temperature": 0.65,
            "max_tokens": 56,
            "messages": [
                {"role": "system", "content": (
                    "Ты помощник управляющего кофейней. Дай одно короткое пояснение "
                    "на русском по данным ниже. Без цифр, новых фактов и встречных вопросов."
                )},
                {"role": "user", "content": (
                    "Вопрос: Дотянем ли до прихода?\nДанные: Дефицит ожидается до поставки."
                )},
                {"role": "assistant", "content": "Приход по графику уже не успеет закрыть раннюю нехватку."},
                {"role": "user", "content": f"Вопрос: {question}\nДанные: {facts}\nПояснение:"},
            ],
        }).strip().strip("«»\"")
        note = re.split(r"(?<=[.!?])\s", note, maxsplit=1)[0]
    except _MODEL_ERRORS:
        return answer
    if not re.fullmatch(r"[А-Яа-яЁё][А-Яа-яЁё ,.!–—:«»()\-]{15,230}[.!]", note):
        return answer
    if re.search(r"\b(?:один|дв[ае]|три|четыр\w*|пят\w*|шест\w*|семь|восемь|девят\w*|десят\w*|двадц\w*|тридц\w*|сто|тысяч\w*)\b", note, re.I):
        return answer
    return answer.model_copy(update={"explanation": note, "model": MODEL})


def respond(dataset: Dataset, shift: ShiftOverview, question: str) -> CopilotAnswer:
    fallback = answer_question(dataset, shift, question)
    endpoint = os.environ.get("COYOTE_LLM_URL")
    if not endpoint or not _slot.acquire(blocking=False):
        return fallback

    try:
        if fallback.kind != "unsupported":
            return explain(endpoint, question, fallback)
        if fallback.source == "Журнал смены":
            return fallback
        query = question.casefold().replace("ё", "е")
        candidates: dict[str, tuple[str, str]] = {}
        if any(word in query for word in ("смен", "перв", "приоритет", "нача", "сосредоточ", "план", "задач")):
            candidates["shift"] = ("план действий", "Что делать первым?")
        if any(word in query for word in ("списа", "потер", "пролив", "пересчит")):
            candidates["loss"] = ("последнее списание", "Что изменилось после списания?")
        candidates.update({
            f"recipe:{sku}": (name, f"Какой состав {aliases[0]}?")
            for sku, name, aliases in DRINKS
            if any(alias in query for alias in aliases) and any(recipe.sku == sku for recipe in dataset.recipes)
        })
        ingredient_aliases = dict(INGREDIENTS)
        for item in shift.forecast.ingredients:
            aliases = ingredient_aliases.get(item.ingredientId, ()) + (item.name.casefold(),)
            if item.ingredientId == "milk":
                aliases += ("молочк",)
            if not any(alias in query for alias in aliases):
                continue
            candidates.update({
                f"stock:{item.ingredientId}": (item.name, f"Сколько осталось: {item.name}?"),
                f"purchase:{item.ingredientId}": (item.name, f"Сколько заказать: {item.name}?"),
                f"shortage:{item.ingredientId}": (item.name, f"Хватит ли до поставки: {item.name}?"),
            })
        if not candidates:
            return fallback
        menu = ", ".join(f"{code} ({label})" for code, (label, _) in candidates.items())
        route = select_route(endpoint, menu, question, ["none", *candidates])
        if route in candidates:
            answer = answer_question(dataset, shift, candidates[route][1])
            if answer.kind == route.split(":")[0]:
                return explain(endpoint, question, answer.model_copy(update={"model": MODEL}))
    except _MODEL_ERRORS:
        _logger.warning("Copilot model response unavailable; using direct lookup")
    finally:
        _slot.release()
    return fallback

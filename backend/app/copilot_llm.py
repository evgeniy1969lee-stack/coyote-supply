"""Use Qwen to select a grounded answer from the current shift."""

import json
import logging
import os
from threading import BoundedSemaphore
from urllib.error import URLError
from urllib.request import Request, urlopen

from .copilot import DRINKS, INGREDIENTS, CopilotAnswer, answer_question
from .data import Dataset
from .shift import ShiftOverview

MODEL = "Qwen2.5-0.5B-Instruct"
_slot = BoundedSemaphore(1)
_logger = logging.getLogger(__name__)


def select_route(endpoint: str, menu: str, question: str, routes: list[str]) -> str:
    schema = {
        "type": "object",
        "properties": {"route": {"type": "string", "enum": routes}},
        "required": ["route"],
        "additionalProperties": False,
    }
    body = {
        "model": MODEL,
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
    request = Request(
        f"{endpoint.rstrip('/')}/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=12) as response:
        completion = json.load(response)
    return json.loads(completion["choices"][0]["message"]["content"])["route"]


def respond(dataset: Dataset, shift: ShiftOverview, question: str) -> CopilotAnswer:
    fallback = answer_question(dataset, shift, question)
    endpoint = os.environ.get("COYOTE_LLM_URL")
    if not endpoint or not _slot.acquire(blocking=False):
        return fallback

    try:
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
            if answer.kind == route.split(":")[0] and (
                fallback.kind == "unsupported" or fallback == answer
            ) and not (fallback.kind == "unsupported" and fallback.source == "Журнал смены"):
                return answer.model_copy(update={"model": MODEL})
    except (URLError, TimeoutError, ValueError, KeyError, TypeError, IndexError):
        _logger.warning("Copilot model response unavailable; using direct lookup")
    finally:
        _slot.release()
    return fallback

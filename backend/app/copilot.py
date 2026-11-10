"""Answer supported shift questions from the current snapshot and active recipe cards."""

from typing import Annotated, Literal

from pydantic import StringConstraints

from .data import Dataset
from .schemas import ContractModel, IngredientForecast
from .shift import ShiftOverview, describe_quantity


class CopilotQuestion(ContractModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=280)]


class CopilotAnswer(ContractModel):
    kind: Literal["recipe", "stock", "purchase", "shortage", "shift", "loss", "unsupported"]
    answer: str
    source: str
    model: Literal["assistant"] | None = None
    explanation: str | None = None


DRINKS = (
    ("oat-latte-300", "Овсяный латте 300 мл", ("овсяный латте", "овсяного латте", "латте на овся", "oat latte")),
    ("latte-300", "Латте 300 мл", ("латте", "latte")),
    ("americano-300", "Американо 300 мл", ("американо", "americano")),
    ("cream-filter", "Фильтр со сливками", ("фильтр",)),
    ("hot-cocoa", "Какао", ("какао", "cocoa")),
    ("vanilla-shot", "Ванильный шот", ("ванильный шот",)),
    ("takeaway-300", "Стакан 300 мл", ("стакан навынос", "стакан на вынос")),
)
INGREDIENTS = (
    ("oat-milk", ("овсян", "oat milk")),
    ("milk", ("молок", "milk")),
    ("cream", ("слив", "cream")),
    ("beans", ("зерн", "beans")),
    ("cups", ("стакан", "cups")),
    ("vanilla", ("сироп", "vanilla")),
    ("cocoa", ("какао", "cocoa")),
)


def purchase_components(item: IngredientForecast) -> str:
    calculation = item.explanation
    if calculation is None:
        return ""
    demand = describe_quantity(calculation.uncoveredWindowDemandQty, item.unit)
    reserve = describe_quantity(max(0, calculation.safetyStockQty - calculation.endStockWithoutOrderQty), item.unit)
    text = f" В расчёте после прихода учтены непокрытый расход {demand} и страховой запас {reserve}."
    if item.recommendedQty is not None and item.recommendedQty > calculation.unroundedOrderQty:
        text += f" Объём округлён до упаковок по {describe_quantity(item.packQty, item.unit)}."
    return text


def answer_question(dataset: Dataset, shift: ShiftOverview, question: str) -> CopilotAnswer:
    text = question.casefold().replace("ё", "е")
    if any(stem in text for stem in ("списа", "потер", "пролив", "пересчит")):
        if any(stem in text for stem in ("недел", "месяц", "вчера", "прошл", "статистик", "динамик", "дней", "дня")):
            return CopilotAnswer(
                kind="unsupported", answer="Доступен журнал текущей смены. Для сравнения периодов нужна история списаний.",
                source="Журнал смены",
            )
        if not shift.recentLosses:
            return CopilotAnswer(kind="loss", answer="В этой смене списаний пока нет.", source="Журнал смены")
        event = shift.recentLosses[0]
        amount = describe_quantity(event.quantity, event.unit)
        opening = describe_quantity(event.before.onHandQty, event.unit)
        remaining = describe_quantity(event.after.onHandQty, event.unit)
        answer = f"{event.name} · списано {amount}. Остаток уменьшился с {opening} до {remaining}."
        if event.before.shortageQty is not None and event.after.shortageQty is not None:
            shortage = describe_quantity(event.after.shortageQty, event.unit)
            if event.before.shortageQty == event.after.shortageQty:
                answer += f" Дефицит до поставки остался {shortage}."
            else:
                previous_shortage = describe_quantity(event.before.shortageQty, event.unit)
                answer += f" Дефицит до поставки изменился с {previous_shortage} до {shortage}."
        if event.after.recommendedQty is not None:
            order = describe_quantity(event.after.recommendedQty, event.unit)
            if event.before.recommendedQty == event.after.recommendedQty:
                answer += f" Рекомендация на период после прихода осталась {order}."
            else:
                answer += f" Новый объём закупки — {order}."
            item = next(item for item in shift.forecast.ingredients if item.ingredientId == event.ingredientId)
            answer += purchase_components(item)
        return CopilotAnswer(kind="loss", answer=answer, source="Журнал смены и пересчёт прогноза")

    purchase = any(word in text for word in ("заказ", "закуп", "купить", "упаков"))
    shortage_question = any(word in text for word in ("дефицит", "нехват", "не хват", "хватит", "до поставки", "до прихода"))
    if not purchase and not shortage_question and not any(word in text for word in ("остал", "склад", "запас", "законч")):
        for sku, name, aliases in DRINKS:
            if not any(alias in text for alias in aliases):
                continue
            recipe = next((
                row for row in dataset.recipes
                if row.sku == sku and row.valid_from <= shift.shiftDate
                and (row.valid_until is None or shift.shiftDate < row.valid_until)
            ), None)
            if recipe is None:
                continue
            usage = [
                f"{dataset.catalog[key].name.lower()} — {describe_quantity(quantity, dataset.catalog[key].unit)}"
                for key, quantity in recipe.usage.items()
            ]
            return CopilotAnswer(
                kind="recipe", answer=f"{name} · {', '.join(usage)}.",
                source=f"Техкарта {recipe.sku} от {recipe.valid_from:%d.%m.%Y}",
            )

    for ingredient_id, aliases in INGREDIENTS:
        if not any(alias in text for alias in aliases):
            continue
        item = next((row for row in shift.forecast.ingredients if row.ingredientId == ingredient_id), None)
        if item is None:
            break
        shortage = next((risk for risk in item.risks if risk.type == "stockout"), None)
        if shortage_question:
            if item.explanation is None:
                answer = f"{item.name} · для оценки дефицита нужно сверить данные."
            elif shortage:
                amount = describe_quantity(shortage.quantity, item.unit)
                answer = f"{item.name} · до поставки не хватит {amount}. Первая нехватка ожидается {shortage.date:%d.%m}."
            else:
                answer = f"{item.name} · прогноз показывает достаточный запас до поставки."
            return CopilotAnswer(kind="shortage", answer=answer, source="Прогноз до ближайшей поставки")
        if purchase:
            if item.recommendedQty is None:
                answer = f"{item.name} · для рекомендации к закупке нужно сверить данные."
            elif item.recommendedQty == 0:
                answer = f"{item.name} · к ближайшей поставке дополнительная закупка не требуется."
            else:
                quantity = describe_quantity(item.recommendedQty, item.unit)
                packs = item.recommendedQty // item.packQty
                answer = f"{item.name} · рекомендуется закупить {quantity} ({packs} уп.)." + purchase_components(item)
            return CopilotAnswer(kind="purchase", answer=answer, source="Расчёт закупки выбранной точки")
        if item.onHandQty is None or any(
            risk.type == "insufficient_data" and risk.reason == "stale_on_hand" for risk in item.risks
        ):
            answer = f"{item.name} · актуальный остаток нужно сверить."
        else:
            answer = f"{item.name} · на складе {describe_quantity(item.onHandQty, item.unit)}."
            if shortage:
                answer += f" Ожидается нехватка с {shortage.date:%d.%m}."
        return CopilotAnswer(kind="stock", answer=answer, source="Склад выбранной точки")

    if purchase or shortage_question:
        return CopilotAnswer(kind="unsupported", answer="Укажите ингредиент, для которого нужен расчёт.", source="Прогноз точки")

    if any(word in text for word in ("смен", "задач", "перв", "приоритет", "план", "что дел")):
        action = next((action for action in shift.actions if action.priority != "done"), None)
        answer = f"{action.title}. {action.detail}" if action else shift.guardian.message
        return CopilotAnswer(kind="shift", answer=answer, source="План Shift Guardian")

    return CopilotAnswer(
        kind="unsupported",
        answer="Могу подсказать состав напитка, остаток, объём закупки, дефицит до поставки или приоритет смены.",
        source="Вопрос вне данных смены",
    )

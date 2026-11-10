"""Inspect a single image and suggest a recipe portion, without writing stock."""

import base64
import io
import json
import os
import re
from dataclasses import dataclass
from threading import BoundedSemaphore
from typing import Literal
from urllib.request import Request as OutgoingRequest, urlopen

from fastapi import Request
from PIL import Image

from .copilot import DRINKS
from .data import Dataset
from .schemas import ContractModel, Id, PositiveQty, Qty
from .shift import VISION_INGREDIENTS, ShiftSnapshot, vision_recipes

MODEL = "SmolVLM-256M-Instruct"
MAX_FRAME_BYTES = 640_000
MAX_FRAME_SIDE = 640
Observation = Literal["possible_pour", "ingredient_visible", "unclear"]
_slot = BoundedSemaphore(1)


class InvalidFrame(ValueError):
    pass


class FrameTooLarge(ValueError):
    pass


class VisionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FrameHint:
    observation: Observation
    ingredient_id: str | None = None


class RecipePortion(ContractModel):
    recipeSku: Id
    recipeName: str
    ingredientId: Id
    ingredientName: str
    recipeQty: PositiveQty
    availableQty: Qty | None


class VisionProposal(ContractModel):
    model: str = MODEL
    observation: Observation
    ingredientId: Id | None
    forecastId: Id
    options: list[RecipePortion]


async def read_frame(request: Request) -> bytes:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "image/jpeg":
        raise InvalidFrame
    frame = bytearray()
    async for chunk in request.stream():
        if len(frame) + len(chunk) > MAX_FRAME_BYTES:
            raise FrameTooLarge
        frame.extend(chunk)
    return bytes(frame)


def decode_jpeg(frame: bytes, *, max_side: int = MAX_FRAME_SIDE) -> Image.Image:
    try:
        with Image.open(io.BytesIO(frame), formats=("JPEG",)) as image:
            if min(image.size) < 32 or max(image.size) > max_side:
                raise InvalidFrame
            return image.convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise InvalidFrame from exc


def _normalized_jpeg(frame: bytes) -> str:
    encoded = io.BytesIO()
    decode_jpeg(frame).save(encoded, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")


def request_caption(endpoint: str, data_url: str) -> str:
    body = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": 52,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": "Describe the visible objects and action in one short sentence."},
            ],
        }],
    }
    request = OutgoingRequest(
        f"{endpoint.rstrip('/')}/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=28) as response:
        return json.load(response)["choices"][0]["message"]["content"]


def _classify_caption(caption: str) -> FrameHint:
    text = caption.casefold()
    if re.search(r"\b(?:no|not|cannot)\b[^.!?]{0,40}\b(?:milk|cream|pour\w*)\b", text):
        return FrameHint("unclear")
    if re.search(r"\boat(?:meal)?[ -]+milk\b", text):
        ingredient = "oat-milk"
    elif re.search(r"\b(?:almond|soy|plant|coconut)[ -]+milk\b", text):
        return FrameHint("unclear")
    elif re.search(r"\bmilk\b", text):
        ingredient = "milk"
    elif re.search(r"\bcream\b(?![- ]colou?r)", text):
        ingredient = "cream"
    else:
        return FrameHint("unclear")
    pouring = re.search(r"\b(?:pour(?:ing|ed|s)?|stream of)\b", text)
    return FrameHint("possible_pour" if pouring else "ingredient_visible", ingredient)


def analyze_frame(frame: bytes) -> FrameHint:
    data_url = _normalized_jpeg(frame)
    endpoint = os.getenv("COYOTE_VISION_URL")
    if not endpoint or not _slot.acquire(blocking=False):
        raise VisionUnavailable
    try:
        return _classify_caption(request_caption(endpoint, data_url))
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise VisionUnavailable from exc
    finally:
        _slot.release()


def make_proposal(dataset: Dataset, snapshot: ShiftSnapshot, hint: FrameHint) -> VisionProposal:
    forecast = snapshot.forecast
    recipes = vision_recipes(dataset, snapshot.store.as_of_date)
    labels = {sku: label for sku, label, _ in DRINKS}
    options = []
    for item in forecast.ingredients:
        if item.ingredientId not in VISION_INGREDIENTS or item.unit != "ml":
            continue
        stale = any(risk.type == "insufficient_data" and risk.reason == "stale_on_hand" for risk in item.risks)
        stock = snapshot.store.inventory[item.ingredientId]
        available = None if stale else item.onHandQty
        if available is not None and stock.lots is not None:
            available = sum(
                lot.quantity for lot in stock.lots
                if lot.expires_on is None or lot.expires_on >= snapshot.store.as_of_date
            )
        for recipe in recipes:
            portion = recipe.usage.get(item.ingredientId)
            if portion is not None:
                options.append(RecipePortion(
                    recipeSku=recipe.sku, recipeName=labels.get(recipe.sku, recipe.sku),
                    ingredientId=item.ingredientId, ingredientName=item.name, recipeQty=portion,
                    availableQty=available,
                ))
    return VisionProposal(
        observation=hint.observation, ingredientId=hint.ingredient_id,
        forecastId=forecast.forecastId, options=options,
    )

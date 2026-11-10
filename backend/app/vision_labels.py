"""Recognize a small ingredient catalogue from printed packaging text."""

import csv
import io
import os
import re
import subprocess
import unicodedata
from functools import lru_cache
from threading import BoundedSemaphore

from PIL import Image, ImageOps
from rapidocr_onnxruntime import RapidOCR
from rapidocr_onnxruntime.utils.infer_engine import ONNXRuntimeError

from .vision import VisionUnavailable, decode_jpeg

_slot = BoundedSemaphore(1)
_OAT = re.compile(
    r"\b(?:oat[\s-]*(?:no dairy[.\s]+)?(?:milk|drink|beverage)|"
    r"oat barista|barista (?:gluten free )?oat|"
    r"напиток овсян\w*|овсян\w* (?:напиток|молоко)|сұлы (?:сусыны|сүті))\b"
)
_OAT_BRAND = re.compile(r"\boat[\s-]?ly\b")
_DAIRY_MILK = re.compile(r"\b(?:cow'?s|whole|skim(?:med)?|fresh|dairy)\s+milk\b")
_MIXED_MILK = re.compile(r"\b[мm][оo][лlλa][оo][кk][оo]\b")
_MILK = re.compile(r"\b(?:milk|молоко|сүт)\b")
_CREAM = re.compile(
    r"\b(?:whipping(?:\s+[\w%.,]+){0,3}\s+(?:cream|cueam)|(?:heavy|double|single|dairy|light|cooking) cream|"
    r"сливки|кілегей|cream\s+\d{2}(?:[.,]\d+)?\s*%)(?!\w)"
)
_OTHER_PRODUCT = re.compile(
    r"\b(?:ice cream|cream(?:er| cheese)|sour cream|iced (?:coffee|latte|macchiato)|"
    r"milkshake|condensed|evaporated|powdered|chocolate milk|oatgurt|yog[hu]*rt|"
    r"мороженое|сметана|қаймақ|йогурт|сгущ[её]нн\w*|сухое молоко|молочный коктейль|қоюландырылған)\b"
)
_OTHER_BASE = re.compile(
    r"\b(?:no[n]?[\s-]*dairy|dairy[\s-]+free|plant[\s-]+based|almond|soy(?:a)?|coconut|"
    r"миндальн\w*|соев\w*|кокосов\w*)\b"
)
_MENTION = re.compile(
    r"\b(?:(?:may )?contains?|not|without|free from|содержит|содержать|без)\s+(?:\w+\s+){0,2}"
    r"(?:milk|молоко|сүт)\b|\b(?:milk|молоко|сүт)[\s-]+free\b"
)


def classify_label(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = " ".join(normalized.split())
    normalized = _MIXED_MILK.sub("молоко", normalized)
    names = _MENTION.sub(" ", normalized)
    if _OTHER_PRODUCT.search(names):
        return None
    oat = bool(_OAT.search(names) or (_OAT_BRAND.search(names) and re.search(r"\bbarista\b", names)))
    cream = bool(_CREAM.search(names))
    milk = bool(_MILK.search(_OAT.sub(" ", names)))

    if oat:
        return None if cream or _DAIRY_MILK.search(names) else "oat-milk"
    if _OTHER_BASE.search(names) or (cream and milk):
        return None
    if cream:
        return "cream"
    return "milk" if milk else None


@lru_cache(maxsize=1)
def _detector() -> RapidOCR:
    return RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1, max_side_len=960, det_limit_type="max")


def _multilingual_text(image: Image.Image) -> str:
    grayscale = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)
    width, height = grayscale.size
    scale = min(2, 1280 / max(width, height))
    processed = grayscale.resize((round(width * scale), round(height * scale)), Image.Resampling.LANCZOS)
    payload = io.BytesIO()
    processed.save(payload, "PNG")
    result = subprocess.run(
        [os.getenv("COYOTE_TESSERACT_PATH", "tesseract"), "stdin", "stdout", "-l", "eng+rus+kaz",
         "--psm", "11", "-c", "user_defined_dpi=200", "tsv"],
        input=payload.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=6, check=True, env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    words = csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t",
                           quoting=csv.QUOTE_NONE)
    return " ".join(row["text"] for row in words if row.get("text") and float(row.get("conf") or "-1") >= 55)


def read_label(frame: bytes) -> str:
    """Use scene text detection first and multilingual OCR on unclear labels."""
    image = decode_jpeg(frame, max_side=1024)
    if not _slot.acquire(blocking=False):
        raise VisionUnavailable
    try:
        try:
            regions, _ = _detector()(frame)
        except (ONNXRuntimeError, MemoryError):
            regions = []
        text = " ".join(value for _, value, score in (regions or []) if score >= 0.80)
        if classify_label(text):
            return text
        return f"{text}\n{_multilingual_text(image)}"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise VisionUnavailable from exc
    finally:
        _slot.release()


def analyze_label(frame: bytes) -> str | None:
    return classify_label(read_label(frame))

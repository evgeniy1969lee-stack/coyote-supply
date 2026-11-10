import pytest

from backend.app.vision_labels import classify_label


@pytest.mark.parametrize(("text", "expected"), [
    ("OAT DRINK\nBARISTA EDITION\nTHIS IS NOT MILK", "oat-milk"),
    ("OAT-LY!\nBARISTA EDITION", "oat-milk"),
    ("OAT- No dairy. MILK BARISTA EDITION", "oat-milk"),
    ("ALPRO BARISTA GLUTEN FREE OAT", "oat-milk"),
    ("НАПИТОК ОВСЯНЫЙ\nБАРИСТА", "oat-milk"),
    ("СҰЛЫ СУСЫНЫ", "oat-milk"),
    ("ОВСЯНОЕ МОЛОКО\n2,5%", "oat-milk"),
    ("FRESH WHOLE MILK", "milk"),
    ("МОЛОКО\nПАСТЕРИЗОВАННОЕ", "milk"),
    ("СҮТ\n2,5%", "milk"),
    ("FOOD MASTER CYT MOΛOKO 2,5%", "milk"),
    ("MOΛOKO", "milk"),
    ("FOOD MASTER CYT MOAOKO 2,5%", "milk"),
    ("КІЛЕГЕЙ 33%", "cream"),
    ("СЛИВКИ\nДЛЯ ВЗБИВАНИЯ", "cream"),
    ("HEAVY WHIPPING CREAM", "cream"),
    ("OPEN Whipping Cueam DARIGOLD", "cream"),
    ("ALMOND NON-DAIRY MILK", None),
    ("COFFEE CREAMER\nCONTAINS MILK", None),
    ("ICE CREAM\nWHOLE MILK", None),
    ("СГУЩЁННОЕ МОЛОКО", None),
    ("КАКАО\nМОЖЕТ СОДЕРЖАТЬ МОЛОКО", None),
    ("СЛИВКИ\nМОЛОКО", None),
    ("OAT DRINK\nWHOLE MILK", None),
    ("OAT-LY!", None),
    ("MILK\nNO DAIRY", None),
    ("OAT DRINK BARISTA ICED COFFEE", None),
    ("СЛИВКИ\nШОКОЛАДНОЕ МОРОЖЕНОЕ", None),
    ("", None),
])
def test_label_classification_requires_product_evidence(text, expected):
    assert classify_label(text) == expected

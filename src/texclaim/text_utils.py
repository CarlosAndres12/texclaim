"""Tokenisation, stopwords and language guessing shared by retrieval and verification."""

from __future__ import annotations

import re

STOPWORDS_EN = frozenset(
    "a an and are as at be been but by for from has have had in into is it its of on or "
    "that the their these this those to was were which with we our can not also than then "
    "such using used use show shows shown paper results result however while both each".split()
)
STOPWORDS_ES = frozenset(
    "a al algo como con cual cuando de del el ella ellos en entre era es esta este esto "
    "estos fue ha han hay la las le les lo los mas mucho muy no nos o para pero por que se "
    "ser si sin sobre su sus también un una uno unos y ya nuestro nuestra resultados".split()
)
STOPWORDS = STOPWORDS_EN | STOPWORDS_ES
_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def content_tokens(text: str, min_len: int = 2) -> list[str]:
    """Lower-cased tokens without stopwords (English and Spanish), de-duplicated in order."""
    seen: dict[str, None] = {}
    for t in tokenize(text):
        if len(t) >= min_len and t not in STOPWORDS:
            seen.setdefault(t, None)
    return list(seen)


def detect_language(text: str) -> str:
    """'en' or 'es' by stopword ratio; defaults to 'en'."""
    toks = tokenize(text)
    if not toks:
        return "en"
    en = sum(t in STOPWORDS_EN for t in toks)
    es = sum(t in STOPWORDS_ES for t in toks)
    return "es" if es > en else "en"

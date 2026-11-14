"""Normalização de texto em português para busca e interpretação."""
from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s%/.,-]")
_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """minúsculas, sem acentos, pontuação de nomes TACO (vírgulas) vira espaço."""
    t = strip_accents(text.lower())
    t = t.replace(",", " ").replace("-", " ").replace("/", " ")
    t = _PUNCT.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


def light_norm(text: str) -> str:
    """minúsculas e sem acentos, preservando pontuação (útil para datas, decimais, '1h20')."""
    return _SPACES.sub(" ", strip_accents(text.lower())).strip()


_IRREGULAR ={"paes": "pao", "maes": "mae", "graos": "grao", "ovos": "ovo", "files": "file"}


def singular(token: str) -> str:
    """Singularização heurística suficiente para casar nomes de alimentos."""
    if token in _IRREGULAR:
        return _IRREGULAR[token]
    if len(token) <= 3:
        return token
    for suf, rep in (("oes", "ao"), ("aes", "ao"), ("ns", "m"), ("res", "r"), ("zes", "z"), ("ses", "s")):
        if token.endswith(suf):
            return token[: -len(suf)] + rep
    if token.endswith("is") and len(token) > 4:
        return token[:-2] + "l"
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


STOPWORDS = {"de", "do", "da", "dos", "das", "com", "sem", "e", "o", "a", "os", "as", "um", "uma", "em", "no", "na", "tipo"}


def tokens(text: str, drop_stop: bool = True) -> list[str]:
    out = [singular(t) for t in normalize(text).split()]
    return [t for t in out if not (drop_stop and t in STOPWORDS)]

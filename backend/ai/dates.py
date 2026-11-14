"""Datas e períodos em português."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from backend.textutil import normalize

WEEKDAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}


def resolve_date_ref(ref: str | None, today: date) -> date:
    """hoje | ontem | anteontem | YYYY-MM-DD | DD/MM[/AAAA] | dia-da-semana (última ocorrência)."""
    if not ref:
        return today
    r = normalize(ref)
    if r in ("hoje", ""):
        return today
    if r == "ontem":
        return today - timedelta(days=1)
    if r == "anteontem":
        return today - timedelta(days=2)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", ref.strip())
    if m:
        d = date(int(m[1]), int(m[2]), int(m[3]))
        return d
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", ref.strip())
    if m:
        year = int(m[3]) if m[3] else today.year
        if year < 100:
            year += 2000
        d = date(year, int(m[2]), int(m[1]))
        if not m[3] and d > today:
            if (d - today).days > 180:  # ex.: em janeiro, "30/12" = dezembro passado
                return date(year - 1, d.month, d.day)
            raise ValueError(f"{d:%d/%m/%Y} é uma data futura.")
        return d
    for name, wd in WEEKDAYS.items():
        if r.startswith(name):
            delta = (today.weekday() - wd) % 7
            if delta == 0 and "passad" in r:
                delta = 7
            return today - timedelta(days=delta)
    raise ValueError(f"Data não reconhecida: {ref}")


_DATE_PATTERNS = [
    (re.compile(r"\banteontem\b"), "anteontem"),
    (re.compile(r"\bontem\b"), "ontem"),
    (re.compile(r"\bhoje\b"), "hoje"),
    (re.compile(r"\b(?:no |na |em |dia )?(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b"), None),
    (re.compile(r"\b(?:na |no )?(segunda|terca|quarta|quinta|sexta|sabado|domingo)(?: feira)?(?: passad[oa])?\b"), None),
]


def extract_date_ref(norm_text: str) -> tuple[str | None, str]:
    """Retorna (referência de data, texto sem a expressão de data)."""
    for pat, value in _DATE_PATTERNS:
        m = pat.search(norm_text)
        if m:
            ref = value or m.group(1)
            return ref, (norm_text[: m.start()] + " " + norm_text[m.end():]).strip()
    return None, norm_text


@dataclass
class Period:
    start: date
    end: date
    label: str
    explicit: bool = True

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def parse_period(norm_text: str, today: date, default_days: int = 7) -> Period:
    t = norm_text
    m = re.search(r"ultim[oa]s? (\d+) (dia|semana|mes|meses)", t)
    if m:
        n = int(m[1])
        days = n * {"dia": 1, "semana": 7, "mes": 30, "meses": 30}[m[2]]
        return Period(today - timedelta(days=days - 1), today, f"últimos {days} dias")
    if re.search(r"semana (passada|anterior)", t):
        start = today - timedelta(days=today.weekday() + 7)
        return Period(start, start + timedelta(days=6), "semana passada")
    if re.search(r"\b(nesta|nessa|esta|essa|desta|dessa) semana\b", t):
        start = today - timedelta(days=today.weekday())
        return Period(start, today, "esta semana")
    if re.search(r"mes (passado|anterior)", t):
        first = today.replace(day=1)
        last_prev = first - timedelta(days=1)
        return Period(last_prev.replace(day=1), last_prev, "mês passado")
    if re.search(r"\b(neste|nesse|este|esse|deste|desse) mes\b", t):
        return Period(today.replace(day=1), today, "este mês")
    if re.search(r"\b(ultimo mes|30 dias|um mes)\b", t):
        return Period(today - timedelta(days=29), today, "últimos 30 dias")
    if re.search(r"\b(semana|7 dias|sete dias)\b", t):
        return Period(today - timedelta(days=6), today, "últimos 7 dias")
    if re.search(r"\banteontem\b", t):
        d = today - timedelta(days=2)
        return Period(d, d, "anteontem")
    if re.search(r"\bontem\b", t):
        d = today - timedelta(days=1)
        return Period(d, d, "ontem")
    if re.search(r"\bhoje\b", t):
        return Period(today, today, "hoje")
    return Period(today - timedelta(days=default_days - 1), today, f"últimos {default_days} dias", explicit=False)

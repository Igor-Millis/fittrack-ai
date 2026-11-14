"""Repositório de alimentos e busca/desambiguação por texto livre."""
from __future__ import annotations

import difflib
import sqlite3
from dataclasses import dataclass, field

from backend.database.connection import transaction
from backend.models.schemas import CustomFoodIn
from backend.nutrition.units import Portion
from backend.services.audit import audit
from backend.textutil import normalize, tokens

PREPARATION_WORDS = {"cru", "crua", "cozido", "cozida", "grelhado", "grelhada", "assado", "assada",
                     "frito", "frita", "refogado", "refogada"}


@dataclass
class Candidate:
    food_id: int
    name: str
    score: float
    via_alias: bool = False


@dataclass
class MatchResult:
    query: str
    candidates: list[Candidate] = field(default_factory=list)
    ambiguous: bool = False

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def found(self) -> bool:
        return bool(self.candidates)


def get_food(conn: sqlite3.Connection, food_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM foods WHERE id=?", (food_id,)).fetchone()
    return dict(row) if row else None


def get_portions(conn: sqlite3.Connection, food_id: int) -> list[Portion]:
    rows = conn.execute("SELECT unit, size, grams, source FROM food_portions WHERE food_id=? ORDER BY unit, grams",
                        (food_id,)).fetchall()
    return [Portion(r["unit"], r["size"], r["grams"], r["source"]) for r in rows]


_cache: dict[int, tuple[int, list[tuple[int, str, set[str], bool]]]] = {}


def _food_index(conn: sqlite3.Connection) -> list[tuple[int, str, set[str], bool]]:
    """Índice em memória (id, nome, tokens, custom); invalidado quando a contagem muda."""
    key = id(conn)
    stamp = conn.execute("SELECT COUNT(*) || '-' || COALESCE(MAX(id),0) FROM foods WHERE active=1").fetchone()[0]
    cached = _cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    rows = conn.execute("SELECT id, name, is_custom FROM foods WHERE active=1").fetchall()
    idx = [(r["id"], r["name"], set(tokens(r["name"])), bool(r["is_custom"])) for r in rows]
    _cache[key] = (stamp, idx)
    return idx


def _correct_tokens(q: list[str], vocab: set[str]) -> list[str]:
    out = []
    for t in q:
        if t in vocab or len(t) < 4:
            out.append(t)
            continue
        close = difflib.get_close_matches(t, vocab, n=1, cutoff=0.8)
        out.append(close[0] if close else t)
    return out


def search_foods(conn: sqlite3.Connection, text: str, limit: int = 8) -> list[Candidate]:
    idx = _food_index(conn)
    q = tokens(text)
    if not q:
        return []
    vocab = set().union(*(f[2] for f in idx)) if idx else set()
    q = _correct_tokens(q, vocab)
    qset = set(q)
    wants_prep = qset & PREPARATION_WORDS
    scored: list[Candidate] = []
    for fid, name, ftoks, custom in idx:
        inter = qset & ftoks
        if not inter:
            continue
        coverage = len(inter) / len(qset)
        precision = len(inter) / max(len(ftoks), 1)
        score = 0.7 * coverage + 0.3 * precision
        first = tokens(name)[0] if ftoks else ""
        if first == q[0]:
            score += 0.15
        if not wants_prep and ftoks & {"cru", "crua"}:
            score -= 0.05  # sem indicação, assume alimento pronto para consumo
        if custom:
            score += 0.05
        scored.append(Candidate(fid, name, round(score, 4)))
    scored.sort(key=lambda c: (-c.score, len(c.name)))
    return scored[:limit]


def match_food(conn: sqlite3.Connection, text: str, limit: int = 6) -> MatchResult:
    norm = normalize(text)
    sing = " ".join(tokens(text, drop_stop=False))
    alias_rows = conn.execute(
        """SELECT a.food_id, f.name, a.priority FROM food_aliases a JOIN foods f ON f.id=a.food_id
           WHERE f.active=1 AND a.alias IN (?, ?) ORDER BY a.priority DESC""",
        (norm, sing),
    ).fetchall()
    result = MatchResult(query=text)
    seen: set[int] = set()
    for r in alias_rows:
        if r["food_id"] not in seen:
            result.candidates.append(Candidate(r["food_id"], r["name"], 1.0 + r["priority"] / 10, True))
            seen.add(r["food_id"])
    for c in search_foods(conn, text, limit=limit + 4):
        if c.food_id not in seen and len(result.candidates) < limit:
            result.candidates.append(c)
            seen.add(c.food_id)

    if not result.candidates:
        return result
    top = result.candidates[0]
    if top.via_alias:
        top_priority = (top.score - 1.0) * 10
        result.ambiguous = top_priority < 8
    else:
        second = result.candidates[1] if len(result.candidates) > 1 else None
        result.ambiguous = top.score < 0.75 or (second is not None and top.score - second.score < 0.08)
    return result


def add_custom_food(conn: sqlite3.Connection, food: CustomFoodIn, origin: str = "ui") -> int:
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO foods (name, norm_name, category, kcal, protein_g, carbs_g, fat_g, fiber_g,
               density_g_ml, source, source_ref, is_custom) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
            (food.name, normalize(food.name), food.category or "Personalizados", food.kcal, food.protein_g,
             food.carbs_g, food.fat_g, food.fiber_g, food.density_g_ml,
             food.source or "Cadastro manual do usuário", f"custom:{normalize(food.name)}"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT OR IGNORE INTO food_aliases (alias, food_id, priority) VALUES (?,?,9)",
                     (normalize(food.name), fid))
        for p in food.portions:
            conn.execute("INSERT INTO food_portions (food_id, unit, size, grams, source) VALUES (?,?,?,?,?)",
                         (fid, p.unit, p.size, p.grams, "Cadastro manual do usuário"))
        audit(conn, "foods", fid, "create", after=food.model_dump(), origin=origin)
    return fid


def add_portion(conn: sqlite3.Connection, food_id: int, unit: str, grams: float, size: str = "medio",
                source: str = "Cadastro manual do usuário") -> None:
    if grams <= 0 or grams > 5000:
        raise ValueError("Gramas da porção devem estar entre 0 e 5000.")
    with transaction(conn):
        conn.execute(
            """INSERT INTO food_portions (food_id, unit, size, grams, source) VALUES (?,?,?,?,?)
               ON CONFLICT(food_id, unit, size) DO UPDATE SET grams=excluded.grams, source=excluded.source""",
            (food_id, unit, size, grams, source),
        )
        audit(conn, "food_portions", food_id, "update", after={"unit": unit, "size": size, "grams": grams})


def set_density(conn: sqlite3.Connection, food_id: int, density: float | None) -> None:
    if density is not None and not (0.2 <= density <= 3):
        raise ValueError("Densidade deve estar entre 0,2 e 3 g/mL.")
    with transaction(conn):
        before = get_food(conn, food_id)
        conn.execute("UPDATE foods SET density_g_ml=? WHERE id=?", (density, food_id))
        audit(conn, "foods", food_id, "update", before={"density_g_ml": before["density_g_ml"]},
              after={"density_g_ml": density})


def add_alias(conn: sqlite3.Connection, alias: str, food_id: int, priority: int = 9) -> None:
    with transaction(conn):
        conn.execute(
            """INSERT INTO food_aliases (alias, food_id, priority) VALUES (?,?,?)
               ON CONFLICT(alias, food_id) DO UPDATE SET priority=excluded.priority""",
            (normalize(alias), food_id, priority),
        )

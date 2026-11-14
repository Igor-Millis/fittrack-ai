"""Motor nutricional determinístico: gramas -> kcal e macronutrientes."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass

from backend.nutrition import foods as food_repo
from backend.nutrition.units import to_grams


@dataclass
class Nutrients:
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float | None = 0.0

    def __add__(self, other: "Nutrients") -> "Nutrients":
        fiber = None if self.fiber_g is None and other.fiber_g is None else (self.fiber_g or 0) + (other.fiber_g or 0)
        return Nutrients(self.kcal + other.kcal, self.protein_g + other.protein_g,
                         self.carbs_g + other.carbs_g, self.fat_g + other.fat_g, fiber)

    def rounded(self) -> "Nutrients":
        return Nutrients(round(self.kcal, 1), round(self.protein_g, 1), round(self.carbs_g, 1),
                         round(self.fat_g, 1), None if self.fiber_g is None else round(self.fiber_g, 1))

    def as_dict(self) -> dict:
        return asdict(self)


def nutrients_for(food: dict, grams: float) -> Nutrients:
    """Valores da tabela são por 100 g. Macro ausente (NA na TACO) conta como 0;
    fibra ausente permanece desconhecida (None)."""
    if grams <= 0:
        raise ValueError("gramas deve ser > 0")
    f = grams / 100.0
    fiber = food.get("fiber_g")
    return Nutrients(
        kcal=food["kcal"] * f,
        protein_g=(food.get("protein_g") or 0) * f,
        carbs_g=(food.get("carbs_g") or 0) * f,
        fat_g=(food.get("fat_g") or 0) * f,
        fiber_g=None if fiber is None else fiber * f,
    )


@dataclass
class ComputedItem:
    food_id: int
    food_name: str
    quantity: float
    unit: str
    grams: float
    basis: str
    nutrients: Nutrients


def compute_item(conn: sqlite3.Connection, food_id: int, quantity: float, unit: str,
                 size: str | None = None, grams_override: float | None = None) -> ComputedItem:
    """Resolve gramas (pode lançar units.ConversionError) e calcula nutrientes."""
    food = food_repo.get_food(conn, food_id)
    if food is None:
        raise ValueError(f"Alimento {food_id} não encontrado.")
    if grams_override:
        grams, basis = grams_override, f"{grams_override:g} g informados"
    else:
        res = to_grams(quantity, unit, density_g_ml=food.get("density_g_ml"),
                       portions=food_repo.get_portions(conn, food_id), size=size, food_name=food["name"])
        grams, basis = res.grams, res.basis
    return ComputedItem(food_id, food["name"], quantity, unit, round(grams, 2), basis, nutrients_for(food, grams))


def total(items: list[ComputedItem]) -> Nutrients:
    acc = Nutrients()
    for it in items:
        acc = acc + it.nutrients
    return acc

"""Unidades de medida e conversão para gramas.

Regras (sem inventar dados):
* massa (g, kg, mg) converte diretamente;
* volume (ml, l, colheres/xícaras de medida) só vira massa se o alimento tiver
  densidade cadastrada (g/mL);
* medidas caseiras (unidade, fatia, concha, porção...) exigem uma porção cadastrada para
  aquele alimento (tabela food_portions). Sem isso, o sistema pergunta os gramas.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.textutil import normalize

MASS_UNITS = {"g": 1.0, "kg": 1000.0, "mg": 0.001}
VOLUME_UNITS_ML = {"ml": 1.0, "l": 1000.0}
# volumes padronizados de utensílios de medida, usados só quando há densidade e não há porção
MEASURE_VOLUME_ML = {"colher de sopa": 15.0, "colher de cha": 5.0, "xicara": 240.0}
HOUSEHOLD_UNITS = {"unidade", "fatia", "porcao", "colher de sopa", "colher de cha", "concha",
                   "xicara", "copo", "pote", "quadrado", "pedaco", "lata", "escumadeira"}

ALL_UNITS = list(MASS_UNITS) + list(VOLUME_UNITS_ML) + sorted(HOUSEHOLD_UNITS)

_SYNONYMS: dict[str, str] = {
    "g": "g", "gr": "g", "grs": "g", "grama": "g", "gramas": "g",
    "kg": "kg", "kgs": "kg", "quilo": "kg", "quilos": "kg", "kilo": "kg", "kilos": "kg", "quilograma": "kg", "quilogramas": "kg",
    "mg": "mg", "miligrama": "mg", "miligramas": "mg",
    "ml": "ml", "mililitro": "ml", "mililitros": "ml",
    "l": "l", "lt": "l", "litro": "l", "litros": "l",
    "unidade": "unidade", "unidades": "unidade", "un": "unidade", "und": "unidade", "unid": "unidade",
    "fatia": "fatia", "fatias": "fatia",
    "porcao": "porcao", "porcoes": "porcao",
    "colher de sopa": "colher de sopa", "colheres de sopa": "colher de sopa", "colher sopa": "colher de sopa",
    "colher de cha": "colher de cha", "colheres de cha": "colher de cha", "colher cha": "colher de cha",
    "colher": "colher de sopa", "colheres": "colher de sopa", "colherada": "colher de sopa",
    "concha": "concha", "conchas": "concha",
    "xicara": "xicara", "xicaras": "xicara",
    "copo": "copo", "copos": "copo",
    "pote": "pote", "potes": "pote", "potinho": "pote",
    "quadrado": "quadrado", "quadrados": "quadrado", "quadradinho": "quadrado",
    "pedaco": "pedaco", "pedacos": "pedaco",
    "lata": "lata", "latas": "lata",
    "escumadeira": "escumadeira", "escumadeiras": "escumadeira",
}


def canonical_unit(raw: str | None) -> str | None:
    if raw is None:
        return None
    return _SYNONYMS.get(normalize(raw))


def unit_synonyms() -> dict[str, str]:
    return dict(_SYNONYMS)


class ConversionError(ValueError):
    """Não há informação confiável para converter a quantidade em gramas."""


@dataclass
class Portion:
    unit: str
    size: str
    grams: float
    source: str


@dataclass
class GramsResult:
    grams: float
    basis: str  # explicação legível da conversão


def to_grams(quantity: float, unit: str, *, density_g_ml: float | None = None,
             portions: list[Portion] | None = None, size: str | None = None,
             food_name: str = "alimento") -> GramsResult:
    if quantity is None or quantity <= 0:
        raise ConversionError("Quantidade deve ser positiva.")
    unit = canonical_unit(unit) or unit
    portions = portions or []

    if unit in MASS_UNITS:
        g = quantity * MASS_UNITS[unit]
        return GramsResult(g, f"{_fmt(quantity)} {unit}")

    if unit in VOLUME_UNITS_ML:
        if not density_g_ml:
            raise ConversionError(
                f"Não há densidade cadastrada para '{food_name}'; informe a quantidade em gramas "
                f"ou cadastre a densidade (g/mL) na página Alimentação."
            )
        ml = quantity * VOLUME_UNITS_ML[unit]
        return GramsResult(ml * density_g_ml, f"{_fmt(ml)} mL × {density_g_ml:g} g/mL")

    if unit in HOUSEHOLD_UNITS:
        same_unit = [p for p in portions if p.unit == unit]
        wanted = size or "medio"
        exact = next((p for p in same_unit if p.size == wanted), None)
        if exact:
            return GramsResult(quantity * exact.grams,
                               f"{_fmt(quantity)} {unit} ({wanted}) ≈ {_fmt(exact.grams)} g cada — {exact.source}")
        if same_unit and size is None:
            p = next((p for p in same_unit if p.size == "medio"), same_unit[0])
            return GramsResult(quantity * p.grams,
                               f"{_fmt(quantity)} {unit} ({p.size}) ≈ {_fmt(p.grams)} g cada — {p.source}")
        if same_unit and size is not None:
            options = ", ".join(f"{p.size}: {_fmt(p.grams)} g" for p in same_unit)
            raise ConversionError(
                f"Não há medida '{unit} {size}' cadastrada para '{food_name}' (disponível: {options}). "
                f"Informe os gramas ou escolha um tamanho cadastrado."
            )
        if unit in MEASURE_VOLUME_ML and density_g_ml:
            ml = quantity * MEASURE_VOLUME_ML[unit]
            return GramsResult(ml * density_g_ml,
                               f"{_fmt(quantity)} {unit} = {_fmt(ml)} mL × {density_g_ml:g} g/mL")
        raise ConversionError(
            f"Não sei quantos gramas tem 1 {unit} de '{food_name}'. Informe o peso em gramas "
            f"(ex.: '{_fmt(quantity)} {unit} = 120 g') ou cadastre a medida caseira."
        )

    raise ConversionError(f"Unidade desconhecida: '{unit}'.")


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")

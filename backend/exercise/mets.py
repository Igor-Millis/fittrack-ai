"""Valores de MET (equivalente metabólico) e cálculo de gasto das atividades.

Referência: Ainsworth BE et al. *2011 Compendium of Physical Activities* (Med Sci Sports
Exerc 43(8):1575-81) e atualização 2024 (Herrmann SD et al., J Sport Health Sci). Os valores
abaixo são os códigos do Compêndio arredondados; para corrida, caminhada e ciclismo o MET é
interpolado pela velocidade quando distância e duração são informadas.

Limitações: METs são médias populacionais para adultos; o gasto real varia com
condicionamento, técnica, terreno, composição corporal e intensidade real.
1 MET ≈ 1 kcal/kg/h (aproximação usada pelo Compêndio).
"""
from __future__ import annotations

from dataclasses import dataclass

# (velocidade km/h, MET) — Compêndio 2011, códigos 12xxx (corrida) e 17xxx (caminhada)
RUNNING_SPEED_MET = [(6.4, 6.0), (8.0, 8.3), (8.4, 9.0), (9.7, 9.8), (10.8, 10.5), (11.3, 11.0),
                     (12.1, 11.8), (12.9, 12.3), (13.8, 12.8), (14.5, 14.5), (16.1, 16.0),
                     (17.7, 19.0), (19.3, 19.8), (20.9, 23.0)]
WALKING_SPEED_MET = [(3.2, 2.8), (4.0, 3.0), (4.8, 3.5), (5.6, 4.3), (6.4, 5.0), (7.2, 7.0), (8.0, 8.3)]
CYCLING_SPEED_MET = [(15.0, 4.0), (17.7, 6.8), (20.9, 8.0), (24.1, 10.0), (28.2, 12.0), (32.0, 15.8)]

# MET por intensidade quando não há velocidade
INTENSITY_MET: dict[str, dict[str, float]] = {
    "musculacao": {"leve": 3.5, "moderada": 5.0, "vigorosa": 6.0},           # 02050/02052/02054
    "corrida": {"leve": 7.0, "moderada": 9.8, "vigorosa": 11.8},              # jogging / ~10 / ~12 km/h
    "caminhada": {"leve": 3.0, "moderada": 3.5, "vigorosa": 5.0},            # 4,0 / 4,8 / 6,4 km/h
    "bicicleta_ergometrica": {"leve": 3.5, "moderada": 6.8, "vigorosa": 8.8},  # 02011/02013/02014
    "ciclismo": {"leve": 4.0, "moderada": 6.8, "vigorosa": 10.0},            # 01010/01020/01040
    "natacao": {"leve": 5.8, "moderada": 7.0, "vigorosa": 9.8},              # 18240/18310/18230
    "esportes": {"leve": 5.0, "moderada": 7.0, "vigorosa": 10.0},            # futebol recreativo..competitivo
    "outra": {"leve": 2.5, "moderada": 4.0, "vigorosa": 6.0},                # genérico (estimativa grosseira)
}

# Esportes/atividades específicos reconhecidos no texto (MET moderado)
SPECIFIC_MET: dict[str, tuple[str, float]] = {
    "futebol": ("esportes", 7.0), "futsal": ("esportes", 7.0), "basquete": ("esportes", 6.5),
    "volei": ("esportes", 4.0), "tenis": ("esportes", 7.3), "beach tennis": ("esportes", 6.0),
    "handebol": ("esportes", 8.0), "jiu jitsu": ("esportes", 10.3), "boxe": ("esportes", 7.8),
    "muay thai": ("esportes", 10.3), "lutas": ("esportes", 10.3), "crossfit": ("outra", 8.0),
    "hiit": ("outra", 8.0), "funcional": ("outra", 6.0), "yoga": ("outra", 2.5), "pilates": ("outra", 3.0),
    "danca": ("outra", 5.0), "zumba": ("outra", 6.5), "pular corda": ("outra", 11.8), "eliptico": ("outra", 5.0),
    "escada": ("outra", 9.0), "remo": ("outra", 7.0), "trilha": ("caminhada", 6.0), "spinning": ("bicicleta_ergometrica", 8.5),
    "alongamento": ("outra", 2.3),
}

SPEED_TABLES = {"corrida": RUNNING_SPEED_MET, "caminhada": WALKING_SPEED_MET, "ciclismo": CYCLING_SPEED_MET}


def interpolate(table: list[tuple[float, float]], speed: float) -> float:
    if speed <= table[0][0]:
        return table[0][1]
    if speed >= table[-1][0]:
        return table[-1][1]
    for (s0, m0), (s1, m1) in zip(table, table[1:]):
        if s0 <= speed <= s1:
            return m0 + (m1 - m0) * (speed - s0) / (s1 - s0)
    return table[-1][1]


@dataclass
class MetChoice:
    met: float
    source: str


def choose_met(activity_type: str, intensity: str | None = None, duration_min: float | None = None,
               distance_km: float | None = None, specific: str | None = None) -> MetChoice:
    if specific and specific in SPECIFIC_MET:
        _, met = SPECIFIC_MET[specific]
        return MetChoice(met, f"Compêndio de Atividades Físicas – {specific}")
    if distance_km and duration_min and activity_type in SPEED_TABLES:
        speed = distance_km / (duration_min / 60)
        met = interpolate(SPEED_TABLES[activity_type], speed)
        return MetChoice(round(met, 2), f"Compêndio (interpolado por velocidade {speed:.1f} km/h)")
    level = intensity or "moderada"
    met = INTENSITY_MET.get(activity_type, INTENSITY_MET["outra"])[level]
    note = "" if intensity else " (intensidade não informada: assumida moderada)"
    return MetChoice(met, f"Compêndio – intensidade {level}{note}")


@dataclass
class ActivityEnergy:
    met: float
    kcal_gross: float
    kcal_net: float


def activity_energy(met: float, weight_kg: float, duration_min: float) -> ActivityEnergy:
    """Bruto = MET × kg × h. Líquido = (MET − 1) × kg × h: desconta o gasto de repouso que
    já está incluído na linha de base diária (evita dupla contagem)."""
    if met <= 0 or weight_kg <= 0 or duration_min <= 0:
        raise ValueError("MET, peso e duração devem ser positivos")
    hours = duration_min / 60
    gross = met * weight_kg * hours
    net = max(met - 1.0, 0.0) * weight_kg * hours
    return ActivityEnergy(met, round(gross, 1), round(net, 1))

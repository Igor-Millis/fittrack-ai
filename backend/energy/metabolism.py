"""Taxa metabólica basal e gasto energético diário estimado.

TMB: Mifflin-St Jeor (1990)
    homens:   10·peso(kg) + 6,25·altura(cm) − 5·idade + 5
    mulheres: 10·peso(kg) + 6,25·altura(cm) − 5·idade − 161

Métodos de gasto diário (configurável no perfil):

1. "sedentario_mais_exercicio" (padrão, recomendado com registro de treinos)
       GET = TMB × fator_sedentário (1,2) + Σ gasto LÍQUIDO das atividades registradas
   O fator 1,2 cobre repouso + termogênese dos alimentos + atividades cotidianas leves.
   O gasto líquido ( (MET−1)·kg·h ) desconta o repouso já incluso na TMB → sem dupla contagem.

2. "fator_atividade"
       GET = TMB × fator do nível de atividade (1,2 a 1,9)
   Os exercícios registrados NÃO são somados, pois o fator já os representa em média.
   Útil para quem não registra todos os treinos.
"""
from __future__ import annotations

from dataclasses import dataclass

ACTIVITY_FACTORS = {"sedentario": 1.2, "leve": 1.375, "moderado": 1.55, "ativo": 1.725, "muito_ativo": 1.9}


def bmr_mifflin(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    if sex not in ("M", "F"):
        raise ValueError("sexo deve ser 'M' ou 'F'")
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if sex == "M" else base - 161


@dataclass
class DailyExpenditure:
    bmr: float
    baseline: float          # TMB × fator (sem exercícios no método 1; total no método 2)
    exercise_net: float      # gasto líquido somado ao dia (0 no método 2)
    exercise_gross_info: float  # gasto bruto apenas informativo
    total: float
    method: str
    weight_used: float


def daily_expenditure(*, sex: str, weight_kg: float, height_cm: float, age: int, method: str,
                      activity_level: str, sedentary_factor: float, exercise_net_kcal: float,
                      exercise_gross_kcal: float = 0.0) -> DailyExpenditure:
    bmr = bmr_mifflin(sex, weight_kg, height_cm, age)
    if method == "fator_atividade":
        baseline = bmr * ACTIVITY_FACTORS[activity_level]
        return DailyExpenditure(bmr, baseline, 0.0, exercise_gross_kcal, baseline, method, weight_kg)
    if method != "sedentario_mais_exercicio":
        raise ValueError(f"método desconhecido: {method}")
    baseline = bmr * sedentary_factor
    return DailyExpenditure(bmr, baseline, exercise_net_kcal, exercise_gross_kcal,
                            baseline + exercise_net_kcal, method, weight_kg)


def suggest_goals(*, sex: str, weight_kg: float, height_cm: float, age: int, activity_level: str,
                  goal: str) -> dict:
    """Sugestão inicial (editável) de metas. Regras simples e documentadas:
    * calorias: GET pelo fator de atividade −20% (emagrecimento), igual (manutenção), +10% (ganho);
    * proteína: 1,6 g/kg (emagrecimento/manutenção) ou 1,8 g/kg (ganho de massa) —
      faixa 1,4–2,0 g/kg citada pela ISSN (Jäger et al., 2017);
    * gordura: 25% das calorias; carboidrato: restante. Fibra: 14 g/1000 kcal (DGA)."""
    tdee = bmr_mifflin(sex, weight_kg, height_cm, age) * ACTIVITY_FACTORS[activity_level]
    kcal = tdee * {"emagrecimento": 0.8, "manutencao": 1.0, "ganho_massa": 1.1}[goal]
    kcal = max(kcal, 1200 if sex == "F" else 1500)
    protein = weight_kg * (1.8 if goal == "ganho_massa" else 1.6)
    fat = kcal * 0.25 / 9
    carbs = max((kcal - protein * 4 - fat * 9) / 4, 0)
    return {"kcal": round(kcal / 10) * 10, "protein_g": round(protein), "carbs_g": round(carbs),
            "fat_g": round(fat), "fiber_g": round(kcal / 1000 * 14), "tdee_estimado": round(tdee)}

"""Modelos Pydantic: validação de toda entrada que chega ao banco ou vem do LLM."""
from __future__ import annotations

from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sex = Literal["M", "F"]
Goal = Literal["emagrecimento", "manutencao", "ganho_massa"]
ActivityLevel = Literal["sedentario", "leve", "moderado", "ativo", "muito_ativo"]
EnergyMethod = Literal["sedentario_mais_exercicio", "fator_atividade"]
MealType = Literal["cafe_da_manha", "lanche_manha", "almoco", "lanche_tarde", "jantar", "ceia", "outro"]
Intensity = Literal["leve", "moderada", "vigorosa"]
ActivityType = Literal["musculacao", "corrida", "caminhada", "bicicleta_ergometrica", "ciclismo",
                       "natacao", "esportes", "outra"]

MEAL_LABELS = {
    "cafe_da_manha": "Café da manhã", "lanche_manha": "Lanche da manhã", "almoco": "Almoço",
    "lanche_tarde": "Lanche da tarde", "jantar": "Jantar", "ceia": "Ceia", "outro": "Outro",
}
ACTIVITY_LABELS = {
    "musculacao": "Musculação", "corrida": "Corrida", "caminhada": "Caminhada",
    "bicicleta_ergometrica": "Bicicleta ergométrica", "ciclismo": "Ciclismo", "natacao": "Natação",
    "esportes": "Esportes", "outra": "Outra atividade",
}
GOAL_LABELS = {"emagrecimento": "Emagrecimento", "manutencao": "Manutenção", "ganho_massa": "Ganho de massa muscular"}
LEVEL_LABELS = {
    "sedentario": "Sedentário (pouco ou nenhum exercício)", "leve": "Levemente ativo (1–3x/semana)",
    "moderado": "Moderadamente ativo (3–5x/semana)", "ativo": "Muito ativo (6–7x/semana)",
    "muito_ativo": "Extremamente ativo (trabalho físico + treinos)",
}


class ProfileIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str | None = Field(default=None, max_length=80)
    sex: Sex
    age: int = Field(ge=10, le=120)
    height_cm: float = Field(ge=100, le=250)
    initial_weight_kg: float = Field(ge=25, le=350)
    activity_level: ActivityLevel
    goal: Goal
    energy_method: EnergyMethod = "sedentario_mais_exercicio"
    sedentary_factor: float = Field(default=1.2, ge=1.0, le=1.6)
    target_weight_kg: float | None = Field(default=None, ge=25, le=350)
    weekly_rate_kg: float | None = Field(default=None, ge=-1.5, le=1.0)


class GoalIn(BaseModel):
    start_date: Date
    kcal: float = Field(ge=800, le=8000)
    protein_g: float = Field(ge=0, le=600)
    carbs_g: float = Field(ge=0, le=1500)
    fat_g: float = Field(ge=0, le=500)
    fiber_g: float | None = Field(default=None, ge=0, le=150)


class PortionIn(BaseModel):
    unit: str
    size: Literal["pequeno", "medio", "grande"] = "medio"
    grams: float = Field(gt=0, le=5000)


class CustomFoodIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=120)
    category: str | None = None
    kcal: float = Field(ge=0, le=950, description="kcal por 100 g")
    protein_g: float = Field(ge=0, le=100)
    carbs_g: float = Field(ge=0, le=100)
    fat_g: float = Field(ge=0, le=100)
    fiber_g: float | None = Field(default=None, ge=0, le=100)
    density_g_ml: float | None = Field(default=None, ge=0.2, le=3)
    source: str | None = Field(default=None, max_length=200)
    portions: list[PortionIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _macros_fit_in_100g(self):
        if self.protein_g + self.carbs_g + self.fat_g > 100.5:
            raise ValueError("Proteína + carboidrato + gordura não podem passar de 100 g por 100 g.")
        return self


class MealItemIn(BaseModel):
    food_id: int
    quantity: float = Field(gt=0, le=10000)
    unit: str
    size: Literal["pequeno", "medio", "grande"] | None = None
    grams_override: float | None = Field(default=None, gt=0, le=10000)


class MealIn(BaseModel):
    date: Date
    meal_type: MealType = "outro"
    time: str | None = None
    notes: str | None = Field(default=None, max_length=500)
    source_text: str | None = Field(default=None, max_length=2000)
    items: list[MealItemIn] = Field(min_length=1, max_length=40)


class ActivityIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    date: Date
    activity_type: ActivityType
    duration_min: float = Field(gt=0, le=1440)
    distance_km: float | None = Field(default=None, gt=0, le=500)
    intensity: Intensity | None = None
    description: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)
    source_text: str | None = Field(default=None, max_length=2000)
    met_override: float | None = Field(default=None, gt=0, lt=30)

    @model_validator(mode="after")
    def _plausible_speed(self):
        if self.distance_km:
            speed = self.distance_km / (self.duration_min / 60)
            if speed > 80:
                raise ValueError(f"Velocidade implausível ({speed:.0f} km/h). Verifique distância e duração.")
        return self


class WeightIn(BaseModel):
    date: Date
    weight_kg: float = Field(ge=25, le=350)
    notes: str | None = Field(default=None, max_length=300)


# ---------------------------------------------------------------- saída estruturada do LLM
class LLMFoodItem(BaseModel):
    food: str = Field(min_length=1, max_length=120)
    quantity: float | None = Field(default=None, gt=0, le=10000)
    unit: str | None = None
    size: Literal["pequeno", "medio", "grande"] | None = None


class LLMActivity(BaseModel):
    activity_type: ActivityType
    duration_min: float | None = Field(default=None, gt=0, le=1440)
    distance_km: float | None = Field(default=None, gt=0, le=500)
    intensity: Intensity | None = None
    description: str | None = None


QueryKind = Literal[
    "status_hoje", "restante_hoje", "consumo_dia", "proteina_periodo", "saldo_periodo",
    "ritmo_peso", "media_periodo", "comparar_semanas", "dias_acima_meta", "proteina_suficiente",
    "relatorio", "peso_atual", "atividades_periodo",
]


class LLMParse(BaseModel):
    """Contrato JSON que o LLM deve devolver. Nada de números calculados: só extração."""
    intent: Literal["registrar_alimentos", "registrar_atividades", "registrar_peso", "consulta",
                    "confirmar", "cancelar", "desfazer", "ajuda", "desconhecido"]
    date_ref: str | None = Field(default=None, description="hoje|ontem|anteontem|YYYY-MM-DD")
    meal_type: MealType | None = None
    foods: list[LLMFoodItem] = Field(default_factory=list, max_length=40)
    activities: list[LLMActivity] = Field(default_factory=list, max_length=10)
    weight_kg: float | None = Field(default=None, ge=25, le=350)
    query: QueryKind | None = None
    period_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("foods", "activities", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return v or []

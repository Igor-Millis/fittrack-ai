"""Gera um banco de DEMONSTRAÇÃO com ~30 dias de uso simulado.

Os registros passam pelo mesmo caminho do chat (interpretação -> rascunho -> confirmação),
portanto também servem como teste de ponta a ponta. Nunca use no seu banco real:

    python scripts/gerar_dados_demo.py data/demo.db
    set FITTRACK_DB=data\\demo.db && streamlit run app/main.py
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BREAKFASTS = [
    "No café da manhã comi 2 pães franceses com 30 g de queijo minas e 200 ml de café",
    "Café da manhã: 2 ovos, 1 fatia de pão de forma integral e 1 banana",
    "No café da manhã comi 40 g de aveia, 1 banana e um iogurte natural",
    "Café da manhã foi 1 tapioca com 2 ovos mexidos e 1 xícara de café",
]
LUNCHES = [
    "No almoço comi 150 g de arroz, 100 g de feijão e 180 g de peito de frango grelhado",
    "Almocei 120 g de arroz integral, 1 concha de feijão, 150 g de patinho , 50 g de alface e 1 colher de sopa de azeite",
    "No almoço comi 200 g de batata doce, 170 g de frango grelhado e 100 g de brócolis",
    "Almoço: 150 g de arroz, 100 g de feijão preto, 150 g de carne moída e 80 g de tomate",
]
SNACKS = [
    "No lanche da tarde comi 1 maçã e 30 g de castanha de caju",
    "Lanche: 1 iogurte natural e 1 banana",
    "No lanche comi 2 fatias de pão de forma com 2 fatias de queijo mussarela",
    "Lanche da tarde: 1 pão de queijo e 1 xícara de café",
]
DINNERS = [
    "No jantar comi 2 ovos, 100 g de arroz e 80 g de feijão",
    "Jantei 150 g de salmão grelhado, 150 g de batata cozida e 100 g de cenoura cozida",
    "No jantar comi 120 g de macarrão com 120 g de carne moída",
    "Jantar: 180 g de frango grelhado, 150 g de mandioca cozida e 100 g de tomate",
]
WORKOUTS = [
    "Fiz musculação por 1 hora e 10 minutos",
    "Corri 5 km em 29 minutos",
    "Caminhei por 45 minutos",
    "Fiz musculação por 1 hora e corri 3 km em 18 minutos",
    "Pedalei por 40 minutos em intensidade moderada",
    "Joguei futebol por 1h30",
]


def generate(db: Path, days: int = 30, seed: int = 7) -> dict:
    os.environ["FITTRACK_DB"] = str(db)
    from backend.ai.assistant import Assistant
    from backend.database.connection import init_db
    from backend.models.schemas import GoalIn, ProfileIn
    from backend.services import records

    rnd = random.Random(seed)
    conn = init_db(db)
    if records.get_profile(conn) is None:
        records.save_profile(conn, ProfileIn(name="Demo", sex="M", age=32, height_cm=178, initial_weight_kg=82,
                                             activity_level="moderado", goal="emagrecimento", target_weight_kg=76,
                                             weekly_rate_kg=-0.5))
        records.save_goal(conn, GoalIn(start_date=date(2000, 1, 1), kcal=2200, protein_g=140, carbs_g=240, fat_g=65,
                                       fiber_g=30))
    today = date.today()
    weight = 82.0
    stats = {"messages": 0, "saved": 0, "issues": []}
    for i in range(days, -1, -1):
        day = today - timedelta(days=i)
        a = Assistant(conn, today=day, now=datetime.combine(day, datetime.min.time()).replace(hour=21))
        msgs = [rnd.choice(BREAKFASTS), rnd.choice(LUNCHES), rnd.choice(DINNERS)]
        if rnd.random() < 0.7:
            msgs.append(rnd.choice(SNACKS))
        if rnd.random() < 0.65:
            msgs.append(rnd.choice(WORKOUTS))
        if rnd.random() < 0.8:
            weight += -0.07 + rnd.uniform(-0.35, 0.35) * 0.6
            msgs.append(f"Hoje acordei com {weight:.1f} kg".replace(".", ","))
        if i in (3, 11):  # dias "esquecidos": sem alimentação registrada
            msgs = [m for m in msgs if "kg" in m]
        for m in msgs:
            stats["messages"] += 1
            r = a.handle(m)
            if r.draft is None:
                stats["issues"].append((m, r.text[:120]))
                continue
            if not r.draft.ready:
                stats["issues"].append((m, r.text[:300]))
                continue
            c = a.confirm(r.draft)
            if c.saved:
                stats["saved"] += 1
            else:
                stats["issues"].append((m, c.text[:200]))
    conn.close()
    return stats


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "demo.db"
    if target.resolve() == (ROOT / "data" / "fittrack.db").resolve():
        sys.exit("Recusado: não gere dados de demonstração no banco principal.")
    s = generate(target)
    print(f"{s['messages']} mensagens, {s['saved']} registros salvos em {target}")
    for m, t in s["issues"]:
        print(" -", m, "=>", t.replace("\n", " "))

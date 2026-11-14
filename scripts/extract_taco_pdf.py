"""Extrai a Tabela 1 (composição centesimal) da TACO 4ª edição (PDF oficial) para CSV.

Fonte: NEPA/UNICAMP. Tabela Brasileira de Composição de Alimentos - TACO, 4ª ed. revisada
e ampliada. Campinas: NEPA-UNICAMP, 2011. "É permitida a reprodução total ou parcial desta
obra, desde que citada a fonte."

Uso:
    python scripts/extract_taco_pdf.py data/nutrition/raw/taco_4ed.pdf data/nutrition/taco_4ed.csv

Requer `pdfplumber` (apenas para esta extração; o aplicativo usa o CSV gerado).
Valores especiais da TACO:
  NA  = não aplicável  -> vazio
  Tr  = traço (quantidade ínfima) -> 0
  *   = amostra não analisada -> vazio
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

CATEGORIES = [
    "Cereais e derivados",
    "Verduras, hortaliças e derivados",
    "Frutas e derivados",
    "Gorduras e óleos",
    "Pescados e frutos do mar",
    "Carnes e derivados",
    "Leite e derivados",
    "Bebidas (alcoólicas e não alcoólicas)",
    "Ovos e derivados",
    "Produtos açucarados",
    "Miscelâneas",
    "Outros alimentos industrializados",
    "Alimentos preparados",
    "Leguminosas e derivados",
    "Nozes e sementes",
]

VALUE = r"(?:\d+(?:,\d+)?[a-z]?|NA|Tr|\*)"
N_VALUES = 11  # umidade, kcal, kJ, proteina, lipidios, colesterol, carbo, fibra, cinzas, Ca, Mg


def parse_value(tok: str) -> float | None:
    tok = tok.strip()
    if tok in ("NA", "*", ""):
        return None
    if tok == "Tr":
        return 0.0
    tok = re.sub(r"[a-z]$", "", tok)
    return float(tok.replace(",", "."))


def extract(pdf_path: Path) -> list[dict]:
    """Extrai por posição das palavras (colunas vazias na TACO não aparecem no texto)."""
    import pdfplumber  # import tardio: dependência só do script

    keys = ["umidade_pct", "energia_kcal", "_kj", "proteina_g", "lipidios_g", "_colesterol",
            "carboidrato_g", "fibra_g", "_cinzas", "_ca", "_mg"]
    rows: list[dict] = []
    category = None
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not text.startswith("Tabela 1") or "Energia" not in text:
                continue
            words = page.extract_words()
            lines: dict[int, list[dict]] = {}
            for w in words:
                lines.setdefault(round(w["top"]), []).append(w)
            ordered = [sorted(lines[k], key=lambda w: w["x0"]) for k in sorted(lines)]
            unit_line = next(l for l in ordered if l[0]["text"] == "Alimento")
            centers = [(w["x0"] + w["x1"]) / 2 for w in unit_line if w["text"].startswith("(")]
            assert len(centers) == N_VALUES, centers
            desc_limit = centers[0] - 22
            started = False
            for line in ordered:
                if line is unit_line:
                    started = True
                    continue
                if not started:
                    continue
                joined = " ".join(w["text"] for w in line)
                if joined in CATEGORIES:
                    category = joined
                    continue
                first = line[0]["text"]
                if not re.fullmatch(r"\d{1,3}", first) or line[0]["x0"] > 110:
                    continue
                desc = " ".join(w["text"] for w in line[1:] if w["x1"] < desc_limit)
                if not desc:
                    continue  # número de página
                values: dict[str, float | None] = {k: None for k in keys}
                for w in line[1:]:
                    if w["x1"] < desc_limit:
                        continue
                    c = (w["x0"] + w["x1"]) / 2
                    idx = min(range(N_VALUES), key=lambda i: abs(centers[i] - c))
                    values[keys[idx]] = parse_value(w["text"])
                rows.append({"taco_id": int(first), "nome": desc, "categoria": category,
                             **{k: v for k, v in values.items() if not k.startswith("_")}})
    return rows


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    rows = extract(Path(sys.argv[1]))
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} alimentos extraídos -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

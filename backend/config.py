"""Configuração central do FitTrack AI.

Valores vêm de variáveis de ambiente (arquivo .env opcional) com padrões seguros.
Configurações editáveis pelo usuário (IA, método energético etc.) ficam na tabela
`settings` do SQLite e são manipuladas por `backend.services.settings_service`.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
NUTRITION_DIR = DATA_DIR / "nutrition"
EXPORT_DIR = DATA_DIR / "exports"
BACKUP_DIR = DATA_DIR / "backups"
LOG_DIR = DATA_DIR / "logs"

TACO_CSV = NUTRITION_DIR / "taco_4ed.csv"
PORTIONS_CSV = NUTRITION_DIR / "porcoes_padrao.csv"
ALIASES_CSV = NUTRITION_DIR / "apelidos.csv"


def _load_dotenv() -> None:
    """Leitor mínimo de .env (evita dependência extra). Não sobrescreve o ambiente."""
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def db_path() -> Path:
    """Caminho do banco. `FITTRACK_DB` permite bancos isolados (testes, demonstração)."""
    return Path(os.environ.get("FITTRACK_DB", str(DATA_DIR / "fittrack.db")))


# Padrões das configurações persistidas (podem ser alterados na página Configurações)
DEFAULT_SETTINGS: dict[str, str] = {
    "ai_enabled": os.environ.get("FITTRACK_AI_ENABLED", "false"),
    "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    "ollama_model": os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
    "ollama_timeout": os.environ.get("OLLAMA_TIMEOUT", "90"),
    "kcal_per_kg": "7700",  # aproximação clássica (≈ 7700 kcal por kg de massa corporal)
    "maintenance_band_kcal": "100",  # |saldo| abaixo disso = manutenção estimada
    "auto_backup_days": "1",  # backup automático na abertura se o último tiver mais de N dias
    "backup_keep": "20",
}

DISCLAIMER = (
    "Valores nutricionais e de gasto energético são **estimativas** baseadas em tabelas "
    "(TACO/NEPA-UNICAMP) e equações populacionais (Mifflin-St Jeor, METs). Não constituem "
    "diagnóstico nem substituem acompanhamento de nutricionista ou médico."
)

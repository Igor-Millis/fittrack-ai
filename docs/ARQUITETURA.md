# Arquitetura e decisões técnicas

## Visão geral
O FitTrack AI separa rigidamente **interpretação** (texto → intenção estruturada) de **cálculo** (números) e de
**persistência** (gravação). Só a camada de serviços (`backend/services/records.py`) grava dados do usuário, e
sempre com objetos Pydantic validados.

```
mensagem ─► rule_parser.parse()  ─┐
           ollama_client (opcional)┴─► LLMParse (Pydantic) ─► ground() ─► merge_parses()
                                                             │
                     assistant.build_draft(): match_food (TACO/apelidos) + to_grams (unidades)
                                          + compute_item (kcal/macros) + preview_activity (METs)
                                                             │  Draft (exibido e editável)
                                    confirmação explícita ───┘
                                                             ▼
                          records.save_meal / save_activity / save_weight (transação + auditoria)
                                                             ▼
                          analytics.daily_summary / period_stats / weight_trend ─► dashboard, relatórios, queries
```

## Decisões (ADR resumidas)

| # | Decisão | Motivo |
|---|---|---|
| 1 | **Streamlit** em vez de React | Projeto 100% Python, manutenção por uma pessoa, sem build de frontend. Visual customizado com CSS + componentes HTML próprios (cards, anel de progresso) e Plotly. |
| 2 | **sqlite3 + SQL explícito** em vez de SQLAlchemy | Esquema pequeno; SQL legível e auditável; migrations versionadas simples (`backend/database/migrations.py`). |
| 3 | **Migrations append-only** com `schema_version` e backup automático antes de migrar | Evolução segura sem perder dados. |
| 4 | **Interpretador por regras sempre disponível**; LLM opcional | Funciona offline e sem modelo; LLM melhora frases livres. Ambos produzem o mesmo contrato `LLMParse`. |
| 5 | **Aterramento** da saída do LLM | Quantidades/durações/pesos que não aparecem na mensagem são descartados → o app pergunta em vez de inventar. |
| 6 | **Confirmação obrigatória** para registrar e excluir | Evita registros errados ou duplicados; o rascunho mostra conversões e fontes. |
| 7 | **Retrato dos nutrientes** em `meal_items` | Alterar a base nutricional não reescreve o histórico silenciosamente. |
| 8 | **Metas versionadas por data** | O histórico é avaliado pela meta vigente em cada dia. |
| 9 | **Fingerprint** por data (itens+gramas / tipo+duração+distância) | Bloqueia duplicação acidental (ex.: confirmar duas vezes); "registrar mesmo assim" disponível. |
| 10 | **Dias sem alimentação = sem saldo** | Consumo 0 geraria déficits falsos de ~2000 kcal. |
| 11 | Gasto = **base sedentária + exercício líquido** (padrão) | Evita dupla contagem do repouso; método alternativo por fator configurável. |
| 12 | Respostas por **templates** a partir do analytics | Garante que todo número exibido veio do banco. |
| 13 | TACO extraída do **PDF oficial** por posição das colunas | Reprodutível e verificável; licença permite reprodução citando a fonte. |
| 14 | Logs técnicos sem conteúdo das mensagens/alimentos/pesos | Privacidade. |
| 15 | Uma conexão SQLite por sessão do navegador, WAL | Simples e seguro para uso local. |

## Esquema do banco
Ver `backend/database/migrations.py` (migration 1). Principais restrições:
- `foods.kcal` 0–950/100 g; macros 0–100 g; densidade 0,2–3 g/mL; `UNIQUE(source, source_ref)`.
- `meal_items.meal_id → meals.id ON DELETE CASCADE`; `food_id → foods.id ON DELETE RESTRICT`.
- `weights.date UNIQUE`, peso 25–350 kg; `activities.duration_min` 0–1440, `met` 0–30.
- `goals.start_date UNIQUE`; `user_profile.id = 1` (perfil único).
- Índices: `meals(date)`, `meals(date, fingerprint)`, `activities(date)`, `activities(date, fingerprint)`,
  `foods(norm_name)`, `food_aliases(alias)`, `audit_log(entity, entity_id)`.

## Fotos de refeições (preparado, não implementado)
Um interpretador de imagem precisaria apenas produzir `LLMFoodItem`s (nome, quantidade estimada) para o mesmo
`build_draft`. O rascunho já exibe a base de cada conversão e exige confirmação; a estimativa visual seria marcada
como aproximada.

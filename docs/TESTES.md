# Testes executados

Ambiente: Windows 10, Python 3.12.10, Streamlit 1.67, pandas 3.1, Pydantic 2.14, Ollama com `qwen2.5:3b` e `qwen2.5:7b`.
Data: 14/11/2026.

```
python -m pytest
137 passed in 62.66s
```

| Arquivo | Testes | O que cobre |
|---|---:|---|
| `test_nutrition.py` | 32 | unidades (massa, volume com/sem densidade, medidas caseiras e tamanhos), cálculo de kcal/macros, macro ausente × fibra desconhecida, integridade do CSV da TACO (597 IDs, valores conhecidos, coerência de Atwater), importação (591), busca/apelidos/erros de digitação, ambiguidade, alimento não encontrado, cadastro personalizado e validação |
| `test_energy.py` | 7 | Mifflin-St Jeor (M/F), gasto bruto × líquido, **ausência de dupla contagem**, método por fator ignora treinos, interpolação de MET por velocidade, METs por intensidade/modalidade, metas sugeridas |
| `test_parser.py` | 42 | exemplos do enunciado (refeições, treinos, peso, perguntas), números por extenso, frações, "150g", alimento + atividade na mesma frase, duas atividades, ritmo → duração, comandos (sim/cancelar/desfazer/ajuda), datas e períodos, aterramento da saída do LLM (descarta quantidades e alimentos inventados), LLM indisponível |
| `test_records.py` | 14 | gravação com retrato de nutrientes, **prevenção de duplicação** (refeição, atividade, peso), correção e exclusão de itens, peso usado na atividade, validação Pydantic e `CHECK` do banco, **persistência após fechar e reabrir**, migrations idempotentes, chaves estrangeiras, auditoria, metas versionadas, backup → restauração → exportação CSV, retenção de backups |
| `test_assistant_analytics.py` | 30 | fluxo do chat (rascunho → confirmação → banco; cancelar não grava), pergunta de quantidade faltante, ambiguidade exige escolha, alimento desconhecido não é inventado, medida caseira desconhecida, corrida sem duração, substituição de peso, duplicata no chat, desfazer com confirmação, data futura recusada, datas passadas, fusão LLM + regras; balanço diário conferido à mão, dias sem registro sem saldo, média móvel, estatísticas do período, tendência e gasto implícito; **11 perguntas históricas** conferidas contra valores conhecidos |
| `test_app_pages.py` | 10 | todas as 7 páginas renderizam via `main.py` (Streamlit `AppTest`), assistente de primeira execução, dashboard mostra o valor do banco, registro completo pelo chat da interface |
| `test_ollama_live.py` | 2 | Ollama real (`qwen2.5:3b`): extração de alimento + atividade sem números inventados; intenção de consulta (pulado se o Ollama não estiver rodando) |

## Erros encontrados e corrigidos durante os testes
- Comentário com `;` quebrava a divisão do SQL das migrations → comentários removidos antes da divisão.
- `merge_asof` falhava por resolução de datas diferente (s × µs) → datas normalizadas para `datetime64[ns]`.
- "almocei arroz" virava "rroz" (prefixo removia a letra "a") → limites de palavra no regex.
- "bike ergométrica" era classificada como ciclismo → prioridade ao termo mais longo.
- Data sem ano no futuro (ex.: "20/12" em novembro) virava o ano anterior em silêncio → agora é recusada
  (exceto virada de ano, > 180 dias).
- Alimento ambíguo era pré-selecionado ("leite" → "Leite, de coco") → agora o usuário escolhe entre as opções.
- Assistente de primeira execução vinha com idade/altura/peso pré-preenchidos → campos vazios e obrigatórios.
- `iniciar.bat` com quebras de linha LF → convertido para CRLF (+ `.gitattributes`).

## Verificação manual (navegador)
Com 30 dias simulados pelo chat (`scripts/gerar_dados_demo.py`, 156 mensagens), os números do dashboard foram
conferidos contra consultas SQL diretas: consumo do dia 1.335 kcal (P 107 / C 111 / G 50), exercício 151,5 kcal,
peso 80,7 kg, média de 30 dias 1.498 kcal em 28 dias registrados, gasto 1.764,5 × 1,2 + 151,5 = 2.269 kcal, saldo 934 kcal.
A segunda execução do gerador sobre o mesmo banco foi bloqueada pela proteção contra duplicação (comportamento esperado).

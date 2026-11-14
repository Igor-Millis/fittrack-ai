# FitTrack AI 🥗

**Assistente pessoal local para alimentação, treinos, peso corporal e balanço energético.**
Converse em português ("comi 150 g de arroz e 180 g de frango", "corri 5 km em 30 min", "estou em déficit hoje?"),
confira o rascunho calculado e confirme — tudo fica num banco SQLite **no seu computador**.

- 🇧🇷 Base nutricional oficial **TACO 4ª ed. (NEPA/UNICAMP)** — 591 alimentos com valores analisados
- 🧮 Cálculos 100% determinísticos (Python): a IA **só interpreta texto**, nunca inventa números
- 🤖 IA local **opcional** via [Ollama](https://ollama.com) — funciona offline sem ela (interpretador por regras)
- 🔒 Sem nuvem, sem assinatura, sem APIs pagas; dados pessoais nunca saem da máquina
- ✅ 137 testes automatizados (unitários, integração com SQLite, interface via `AppTest` e Ollama real opcional)

📝 Artigo sobre as decisões do projeto: [FitTrack AI: um diário nutricional com IA que não inventa números](https://igor-millis.github.io/pt/research/fittrack-ai/) ([EN](https://igor-millis.github.io/research/fittrack-ai/))

> ⚠️ Valores nutricionais e gasto energético são **estimativas** (tabelas e equações populacionais).
> O FitTrack AI não faz diagnóstico e não substitui nutricionista ou médico.

---

## Sumário
1. [Como iniciar](#1-como-iniciar) · 2. [Como usar](#2-como-usar) · 3. [IA local (Ollama)](#3-ia-local-ollama-opcional) ·
4. [Backup e exportação](#4-backup-e-exportação) · 5. [Arquitetura](#5-arquitetura) · 6. [Metodologia](#6-metodologia-de-cálculo) ·
7. [Base nutricional e licenças](#7-base-nutricional-e-licenças) · 8. [Testes](#8-testes) · 9. [Limitações](#9-limitações-conhecidas) ·
10. [Roadmap](#10-pendências-e-próximos-passos)

---

## 1. Como iniciar

**Requisitos:** Windows 10/11 (ou Linux/macOS), Python 3.11+ (testado no 3.12). Internet só na primeira instalação.

### Windows (recomendado)
1. Coloque a pasta num caminho **curto**, ex.: `C:\fittrack-ai` (caminhos muito longos quebram DLLs do `pyarrow`).
2. Dê dois cliques em **`iniciar.bat`**. Na primeira vez ele cria `.venv` e instala as dependências (~2 min).
3. O navegador abre em **http://localhost:8501**. Para encerrar, feche a janela do terminal.

### Manual (qualquer sistema)
```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/main.py       # http://localhost:8501
```

### Primeira execução
Um assistente de configuração pede **sexo (para a equação), idade, altura, peso, nível de atividade e objetivo**
(campos começam vazios — nada é presumido) e sugere metas de calorias/macros que você pode editar. Tudo pode ser
alterado depois em **Configurações**.

### Quer só ver funcionando?
```bash
python scripts/gerar_dados_demo.py data/demo.db      # 30 dias simulados, passando pelo chat
set FITTRACK_DB=data\demo.db && streamlit run app/main.py
```

---

## 2. Como usar

| Página | O que faz |
|---|---|
| **Dashboard** | Anel de calorias × meta, gasto estimado, saldo do dia, macros, refeições/atividades de hoje, peso; tendências com filtros (hoje, 7, 30, 90 dias, personalizado) |
| **Assistente** | Chat: registrar, corrigir no cartão de rascunho, confirmar, desfazer e perguntar sobre o histórico |
| **Alimentação** | Diário por dia (editar quantidades, excluir), adicionar manualmente, pesquisar a base, medidas caseiras/densidade, importar CSV, cadastrar alimento |
| **Exercícios** | Registro manual, histórico com MET/fonte/ritmo, gráfico por tipo, explicação do cálculo |
| **Peso corporal** | Pesagens, média móvel 7 dias, variação semanal/mensal, tendência e comparação observado × estimado |
| **Relatórios** | Médias, dias em déficit/superávit, saldo acumulado, consistência, frequência de treino, comparativo semanal, resumo em linguagem natural, comparação entre dois períodos, CSV |
| **Configurações** | Perfil, metas versionadas por data, IA local, parâmetros, backup/restauração, exportação, histórico de alterações |

### Registrar uma refeição
No **Assistente**, escreva naturalmente:
```
Comi 150 g de arroz, 100 g de feijão e 180 g de peito de frango
No café da manhã comi dois pães franceses com 30 g de queijo
Ontem no jantar comi 2 ovos e 1 fatia de pão de forma integral
```
O assistente identifica alimentos, quantidades e unidades, consulta a TACO e mostra um **rascunho** com kcal,
proteínas, carboidratos e gorduras por item. No cartão você pode trocar o alimento (há opções quando o nome é
ambíguo), corrigir quantidade/unidade ou informar os gramas exatos. Clique **Confirmar registro** (ou responda
`sim`). **Nada é salvo sem confirmação.**

Unidades: g, kg, mg, ml, l, unidade, fatia, porção, colher de sopa/chá, concha, xícara, copo, pote, pedaço...
Se a quantidade faltar ou não houver medida caseira cadastrada para o alimento, o assistente **pergunta**.
Volume (ml) só vira gramas quando o alimento tem densidade cadastrada.

### Registrar um treino
```
Hoje fiz musculação por 1 hora e 20 minutos
Corri 5 km em 30 minutos
Pedalei 25 minutos em intensidade moderada
Fiz musculação por 1 hora e corri 3 km em 18 minutos
Joguei futebol por 1h30
```
O gasto é estimado por METs (com interpolação pela velocidade em corrida/caminhada/ciclismo). Se faltar a duração,
o assistente pergunta.

### Peso
`Hoje acordei com 71,2 kg` — um registro por dia (substituir exige confirmação).

### Perguntas (respondidas com dados do banco)
```
Estou em déficit hoje?                       Quanto ainda posso comer hoje?
Quantas calorias consumi ontem?              Quanto consumi de proteína nesta semana?
Qual foi meu déficit acumulado nos últimos 7 dias?   Estou perdendo peso no ritmo esperado?
Qual foi minha média de calorias nos últimos 30 dias?   Compare esta semana com a anterior
Quais dias fiquei acima da minha meta?       Estou comendo proteína suficiente?
Relatório do mês                             apagar o último registro   ·   ajuda
```

---

## 3. IA local (Ollama) — opcional

Sem IA, o **interpretador por regras** em português cobre os exemplos acima e funciona offline.
Com IA, mensagens mais livres são entendidas melhor.

1. Instale o Ollama: https://ollama.com/download
2. Baixe um modelo (o app **não** baixa modelos automaticamente):
   ```bash
   ollama pull qwen2.5:3b     # ~1,9 GB, rápido (recomendado para CPU)
   ollama pull qwen2.5:7b     # ~4,7 GB, mais preciso
   ```
3. No app: **Configurações → IA local (Ollama)** → ative, confira o endereço (`http://localhost:11434`), escolha o
   modelo, ajuste o tempo máximo e use **Testar interpretação**.

**Como a IA é contida:**
- O modelo recebe só a mensagem e devolve JSON no esquema `LLMParse` (formato estruturado do Ollama, temperatura 0).
- O Pydantic valida; depois o JSON é **aterrado** no texto: quantidades/durações/pesos que não aparecem na mensagem
  são descartados, e alimentos que não estão na mensagem são removidos. Campos faltantes são completados pelo
  interpretador por regras ou **perguntados** ao usuário.
- A IA não acessa o banco, não gera SQL e não calcula nada; registro só por funções controladas e após confirmação.
- Respostas às perguntas são montadas por templates a partir do motor analítico.
- Se o Ollama estiver desligado ou demorar além do limite, o app usa as regras automaticamente.
- O 1º uso após ligar o Ollama pode levar 20–60 s (carregamento do modelo na memória).

---

## 4. Backup e exportação

- **Automático:** ao abrir o app, se o último backup tiver mais de 1 dia (configurável), um backup é criado em
  `data/backups/` (mantém os 20 mais recentes).
- **Manual:** Configurações → Backup e exportação → *Criar backup agora* / *Baixar backup*.
- **Restaurar:** escolha o backup e confirme. Antes, o estado atual é salvo como `..._pre-restore.db`.
- **Antes de migrations** do esquema, um backup `..._pre-migration.db` é feito automaticamente.
- **Exportação CSV:** gera um `.zip` com um CSV por tabela (`;`, UTF-8 com BOM — abre direto no Excel).
- **Cópia manual:** com o app fechado, copie `data/fittrack.db` para onde quiser (pendrive, nuvem pessoal).

---

## 5. Arquitetura

```
Usuário ──► Streamlit (app/) ──► Assistente (backend/ai) ──► interpretação: Ollama (opcional) ou regras
                 │                        │                         │ JSON validado (Pydantic) + aterramento
                 │                        ▼                         ▼
                 │              Rascunho ◄── motor nutricional (TACO, unidades) / METs / metabolismo
                 │                        │ confirmação explícita
                 ▼                        ▼
         Analytics (pandas) ◄──── Serviços de registro (records) ──► SQLite (migrations, auditoria, backup)
```

```
fittrack-ai/
├── app/                      # Interface Streamlit
│   ├── main.py               # entrada, navegação, primeira execução
│   ├── pages/                # dashboard, chat, alimentacao, exercicios, peso, relatorios, configuracoes
│   ├── components/           # ui.py (cards, anel, filtros), charts.py (Plotly)
│   └── styles/theme.css
├── backend/
│   ├── config.py             # caminhos, .env, padrões
│   ├── textutil.py           # normalização PT-BR
│   ├── database/             # connection, migrations versionadas, backup/restauração/exportação
│   ├── models/schemas.py     # Pydantic: entradas e contrato JSON do LLM
│   ├── nutrition/            # units, foods (busca/ambiguidade), calculator, importer
│   ├── exercise/mets.py      # Compêndio de METs, interpolação, bruto × líquido
│   ├── energy/metabolism.py  # Mifflin-St Jeor, métodos de gasto, sugestão de metas
│   ├── analytics/daily.py    # balanço diário, períodos, média móvel, tendência do peso
│   ├── services/             # records (únicas funções que gravam), auditoria, settings, chat, manutenção
│   └── ai/                   # rule_parser, ollama_client, assistant, queries, dates
├── data/nutrition/           # taco_4ed.csv, apelidos.csv, porcoes_padrao.csv
├── scripts/                  # extract_taco_pdf.py, gerar_dados_demo.py
├── tests/                    # pytest (137 testes)
├── docs/                     # ARQUITETURA.md, METODOLOGIA.md, TESTES.md
├── iniciar.bat · requirements.txt · .env.example
```

**Banco (SQLite, `data/fittrack.db`)** — tabelas `user_profile`, `goals` (versionadas por data), `foods`,
`food_aliases`, `food_portions`, `meals`, `meal_items` (retrato dos nutrientes no momento do registro),
`activities`, `weights` (1 por dia), `audit_log`, `settings`, `chat_messages`, `schema_version`.
Chaves estrangeiras ativas, `CHECK` de faixas plausíveis, índices por data, WAL, transações atômicas,
impressão digital (`fingerprint`) contra duplicação acidental. Detalhes em [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

**Tecnologias:** Python 3.12 · Streamlit 1.67 · SQLite (sqlite3) · pandas · Plotly · Pydantic 2 · requests ·
Ollama (opcional) · pytest. *SQLAlchemy não foi usado:* o esquema é pequeno e o `sqlite3` com SQL explícito e
migrations versionadas é mais simples de auditar.

---

## 6. Metodologia de cálculo

- **Nutrientes:** valores por 100 g × gramas/100. Macro ausente na TACO (NA) conta 0; fibra ausente fica "desconhecida".
- **TMB:** Mifflin-St Jeor — `10·kg + 6,25·cm − 5·idade + 5` (M) ou `− 161` (F).
- **Gasto diário (padrão, sem dupla contagem):** `TMB × 1,2` (linha de base sedentária, configurável) **+ Σ gasto
  líquido** dos treinos registrados. Líquido = `(MET − 1) × kg × h` (o repouso já está na linha de base).
- **Alternativa:** `TMB × fator do nível de atividade` (1,2–1,9), sem somar treinos — para quem não registra tudo.
- **Saldo:** `gasto − consumo` (positivo = déficit, negativo = superávit, |saldo| ≤ 100 kcal = manutenção).
  **Dias sem alimentação registrada não têm saldo** (evita déficits fictícios).
- **Peso:** média móvel de 7 dias, tendência por regressão linear e comparação com o esperado pelo saldo
  (~7.700 kcal/kg, apenas referência). Com ≥ 8 pesagens em ≥ 14 dias e ≥ 10 dias registrados, o app estima o
  **gasto implícito pela tendência real** e avisa se o estimado parece alto/baixo.

Mais em [docs/METODOLOGIA.md](docs/METODOLOGIA.md).

---

## 7. Base nutricional e licenças

- **TACO 4ª edição** (NEPA/UNICAMP, 2011): extraída do PDF oficial com `scripts/extract_taco_pdf.py`
  (597 linhas validadas: IDs 1–597, coerência de Atwater conferida). A publicação declara: *"É permitida a reprodução
  total ou parcial desta obra, desde que citada a fonte."* Fonte: NEPA-UNICAMP. Tabela Brasileira de Composição de
  Alimentos – TACO. 4. ed. rev. e ampl. Campinas: NEPA-UNICAMP, 2011.
  Seis itens marcados como não analisados na TACO (ex.: *Leite, de vaca, integral*) **não** foram importados —
  cadastre-os pelo rótulo.
- **TBCA (USP/FoRC):** não é redistribuída aqui (os termos não autorizam redistribuição em massa). O app importa
  qualquer CSV (Alimentação → Base → Importar) para quem tiver direito de uso.
- **Medidas caseiras** (`porcoes_padrao.csv`) são aproximações de referência, sempre exibidas no rascunho e editáveis.
- **Código:** MIT (ver `LICENSE`).

Para reextrair a TACO: baixe o PDF oficial (ex.: site do CFN/NEPA) para `data/nutrition/raw/taco_4ed.pdf`,
`pip install -r requirements-dev.txt` e rode `python scripts/extract_taco_pdf.py data/nutrition/raw/taco_4ed.pdf data/nutrition/taco_4ed.csv`.

---

## 8. Testes

```bash
python -m pytest            # 137 testes; os 2 com Ollama real são pulados se ele não estiver rodando
```
Cobrem: cálculo de calorias e macros, conversão de unidades, densidade/medidas caseiras, TMB, METs, bruto × líquido,
dupla contagem, déficit/superávit, médias móveis, tendência, registro de refeições/exercícios/peso, persistência após
reabrir o banco, migrations, chaves estrangeiras, auditoria, backup/restauração/exportação, interpretação de mensagens,
ambiguidades, prevenção de duplicação, consultas históricas, aterramento da saída do LLM e renderização de todas as
páginas (Streamlit `AppTest`), incluindo um registro completo pelo chat da interface. Resultado: [docs/TESTES.md](docs/TESTES.md).

---

## 9. Limitações conhecidas

- Estimativas: TACO tem variação natural entre amostras; METs são médias populacionais (musculação é especialmente imprecisa);
  Mifflin-St Jeor tem erro individual de ~±10%.
- A TACO não tem vários industrializados (whey, iogurtes de marca, leite integral fluido): cadastre pelo rótulo.
- O interpretador por regras entende frases comuns; frases muito livres funcionam melhor com o Ollama ativo.
- Medidas caseiras padrão cobrem ~40 alimentos; para os demais informe gramas ou cadastre a medida.
- Idade não é atualizada automaticamente com o tempo (edite no perfil).
- A interface é otimizada para desktop; funciona no celular via rede local, mas não é um app nativo.
- Fotos de refeições ainda não foram implementadas (ver roadmap).
- No Windows, caminhos de pasta muito longos impedem o carregamento do `pyarrow` (use `C:\fittrack-ai`).

## 10. Pendências e próximos passos

- **Fotos de refeições:** a arquitetura está preparada (o rascunho aceita itens vindos de qualquer interpretador);
  falta um interpretador de imagem com modelo de visão local (ex.: `llava`/`qwen2.5-vl` no Ollama). A estimativa
  visual será sempre marcada como aproximada e exigirá confirmação.
- Leitura de código de barras / tabela nutricional de rótulos.
- Mais medidas caseiras com fonte documentada (ex.: POF/IBGE).
- Refeições favoritas ("repetir o café de ontem").
- Tema escuro dedicado.
- Demonstração pública: `deploy/huggingface/` tem Dockerfile e cabeçalho prontos para um Space Docker com dados
  fictícios (copie os dois arquivos para a raiz do Space). Hoje Spaces Docker em CPU gratuita exigem assinatura PRO.

---
Feito com Python e cuidado com seus dados. Contribuições são bem-vindas.

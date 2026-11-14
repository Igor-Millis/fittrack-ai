# Metodologia e limitações dos cálculos

## Nutrientes
`valor = valor_por_100g × gramas / 100` com dados da TACO (ou cadastros do usuário).
- `NA` (não aplicável) e `Tr` (traço) da TACO → 0 para macros; fibra ausente permanece desconhecida (não somada como 0 nos textos).
- Alimentos marcados `*` (não analisados) na TACO não são importados.

### Conversão de unidades
| Unidade | Regra |
|---|---|
| g, kg, mg | direta |
| ml, l | só com densidade (g/mL) cadastrada no alimento; infusões (café/chá, ≥ 97% água) têm 1,0 g/mL |
| unidade, fatia, concha, porção, pote... | só com medida caseira cadastrada para aquele alimento (tamanho pequeno/médio/grande) |
| colher de sopa/chá, xícara | medida cadastrada; se não houver e o alimento tiver densidade: 15 / 5 / 240 mL × densidade |
| qualquer outra situação | o app **pergunta** os gramas |

## Metabolismo basal
Mifflin MD, St Jeor ST, et al. *Am J Clin Nutr* 1990;51:241-7.
`TMB = 10·peso + 6,25·altura − 5·idade + s`, s = +5 (masculino) ou −161 (feminino).
O peso usado em cada dia é o último registrado até a data (ou o peso do perfil).

## Gasto energético diário
**Método 1 — base sedentária + exercício líquido (padrão)**
`GET = TMB × fator_sedentário (1,2) + Σ (MET − 1) × peso × horas`

O fator 1,2 representa repouso + efeito térmico dos alimentos + atividades leves do dia. Durante um treino, o corpo
continuaria gastando ~1 MET mesmo em repouso; esse valor já está na base, por isso somamos apenas o **líquido**.
Somar o bruto seria **dupla contagem**.

**Método 2 — fator de atividade**
`GET = TMB × fator (1,2 sedentário · 1,375 leve · 1,55 moderado · 1,725 ativo · 1,9 muito ativo)`
Treinos registrados ficam apenas informativos (não somados), pois o fator já os representa.

## METs
Ainsworth BE et al. *2011 Compendium of Physical Activities*; Herrmann SD et al. *2024 Adult Compendium*.
- Corrida, caminhada, ciclismo: com distância e duração, interpolação linear do MET pela velocidade.
- Sem velocidade: MET por intensidade (leve/moderada/vigorosa); sem intensidade informada assume moderada (indicado na fonte).
- Modalidades específicas (futebol, natação, yoga, HIIT...) têm MET próprio.

## Balanço energético
`saldo = GET − consumo` · positivo = déficit · negativo = superávit · |saldo| ≤ 100 kcal = manutenção (configurável).
- Dias sem alimentação registrada: saldo **indefinido** (fora das médias e somas).
- Saldo semanal/mensal = soma dos dias com registro; médias = média dos dias com registro.

## Peso: estimado × observado
- Média móvel de 7 dias (janela de calendário com as pesagens disponíveis).
- Tendência: inclinação da regressão linear das pesagens (kg/semana).
- Esperado pelo saldo: `−saldo_médio × 7 / 7700` kg/semana — **apenas referência**; a composição da perda/ganho
  (água, glicogênio, gordura, massa magra) varia e o modelo de 7.700 kcal/kg é uma simplificação conhecida.
- Gasto implícito (com ≥ 8 pesagens em ≥ 14 dias e ≥ 10 dias registrados):
  `GET_observado = consumo_médio − (tendência_kg/dia × 7700)`. Diferença > 150 kcal/dia gera alerta de que o
  gasto estimado está alto/baixo ou de que há consumo não registrado.

## Sugestão inicial de metas (editável)
- Calorias: GET (fator de atividade) × 0,8 (emagrecimento) / 1,0 (manutenção) / 1,1 (ganho); mínimo 1200 (F) / 1500 (M).
- Proteína: 1,6 g/kg (1,8 g/kg no ganho de massa) — dentro da faixa 1,4–2,0 g/kg (Jäger et al., ISSN 2017).
- Gordura 25% das kcal; carboidrato = restante; fibra 14 g/1000 kcal.

## Limites de validade
Estimativas populacionais para adultos saudáveis. Não usar para gestantes, crianças, atletas de elite ou condições
clínicas sem orientação profissional. O app não faz diagnóstico.

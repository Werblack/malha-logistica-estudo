# Malha Logística SP — Ógea × PagResolve

Estudo de malha logística: quais polos PagResolve podem virar HUB estratégico, até quantos km atendem,
e quanto do volume hoje atendido pela transportadora Ógea a PagResolve consegue absorver — num mapa real,
configurável, com Machine Learning de apoio.

**Escopo dos dados:** julho/2026, estado de São Paulo (`MALHA INPO TO BE.xlsx` + `Prestador de Serviço.csv`).
Todo parâmetro do simulador vem do dado (com a origem explícita na tela) ou é input do usuário — nada é inventado.

## Como rodar

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .

# 1) gera os parquets limpos + geocodifica os polos (cacheado; ~1 min na 1ª vez)
.venv\Scripts\python -m malha.build

# 2) abre a tela única do estudo
.venv\Scripts\streamlit run app/Home.py
```

`python -m malha.build --offline` roda sem internet (usa o cache de geocodificação ou a sede do município).
`--refresh-geo` força baixar de novo os dados do IBGE e refazer a geocodificação.

## O que a tela mostra

Uma única página, com os parâmetros na barra lateral (cada um rotulado com a origem: **dado** observado
em julho/26, ou **input** livre) e 4 abas:

- **Mapa** — municípios coloridos por status (100% Ógea, misto, 100% polo, absorvido no cenário), polos com
  círculo de raio (km, via slider), fluxos de OS absorvida, armazém da Ógea. Export do cenário em Excel.
- **Polos e rateio** — o que cada polo atende hoje vs. no cenário (técnicos a contratar, CMU, ocupação),
  curva de rateio de custo por volume, e overrides manuais de share Ógea por município.
- **Machine Learning** — raio de SLA aprendido (lead time × distância), demanda órfã agrupada em hubs
  candidatos, e score de "HUB estratégico" por polo.
- **Qualidade dos dados** — todas as checagens automáticas do `build` (CEP, datas, distritos da capital,
  preços, técnicos, geocodificação).

## Motor de decisão

`src/malha/optimize.py` resolve um MILP (localização de instalações com capacidade, PuLP/HiGHS) em dois modos:
**Simular** (só abre/fecha o que você travar manualmente) e **Otimizar** (o modelo escolhe polos e técnicos
para reduzir a dependência da Ógea ao menor custo). Ver `tests/test_optimize.py` para os casos verificados
à mão, e a seção *Motor* no plano do estudo para a formulação completa.

## Estrutura

```
src/malha/
  textnorm.py          normalização de texto/CEP/código de polo
  ingest/               leitura das abas BD, TEMPLATE, CMU e do cadastro de prestadores
  geo/                  municípios/polígonos IBGE, geocodificação (com cache), distância haversine
  build.py              pipeline completo: planilhas → parquets + relatório de qualidade
  baseline.py           KPIs atuais e defaults dos parâmetros (tudo derivado do dado)
  costs.py               curva de rateio de custo por volume
  scenario.py            parâmetros do simulador (imutável, serializável)
  optimize.py             MILP de localização com capacidade
  ml/                    raio de SLA, clustering de demanda órfã, score de hub
  viz/map.py              mapa Folium
  report.py               export do cenário em Excel
app/Home.py               tela única (Streamlit)
tests/                    pytest (normalização, custos, otimizador)
```

## Testes

```powershell
.venv\Scripts\pytest -q
```

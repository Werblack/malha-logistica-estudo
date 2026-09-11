# Malha Logística SP (Ógea × PagResolve)

Simulador de malha logística: quais polos PagResolve podem virar HUB estratégico, até quantos km atendem,
e quanto do volume hoje atendido pela transportadora Ógea a PagResolve consegue absorver — num mapa real,
configurável, com resposta instantânea ao mexer nos controles.

**Escopo dos dados:** julho/2026, estado de São Paulo (`MALHA INPO TO BE.xlsx` + `Prestador de Serviço.csv`).
Todo parâmetro do simulador vem do dado (com a origem explícita na tela) ou é input do usuário — nada é inventado.

## Como rodar

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .

# 1) gera os parquets limpos + geocodifica os polos (cacheado; ~1 min na 1ª vez)
.venv\Scripts\python -m malha.build

# 2) app desktop nativo (recomendado — janela própria, sem navegador)
.venv\Scripts\python desktop\main.py

# alternativa: mesma lógica, na Streamlit (navegador)
.venv\Scripts\streamlit run app/Home.py
```

`python -m malha.build --offline` roda sem internet (usa o cache de geocodificação ou a sede do município).
`--refresh-geo` força baixar de novo os dados do IBGE e refazer a geocodificação.

O app desktop usa o motor Edge WebView2 do Windows (já vem instalado por padrão no Windows 10/11) e tiles
do OpenStreetMap para o mapa de fundo — precisa de internet para o mapa carregar; o cálculo em si roda
100% local. Sem internet, o mapa aparece sem o fundo cartográfico, mas o simulador funciona normalmente.

## App desktop (`desktop/`) — interface principal

Janela nativa (PyWebView + MapLibre GL, tema claro), tela única:

- **Mapa** — municípios e os 6 bairros da capital coloridos num gradiente contínuo verde (Ógea) → amarelo
  (PagResolve), proporcional ao share real de cada local (nunca "100% PagResolve" só porque houve uma OS
  de polo lá). Raio de cada polo como círculo real (km), polos como marcadores, armazém da Ógea.
  Basemap OpenStreetMap real (ruas, cidades vizinhas, relevo).
- **Sliders sempre visíveis** — raio global (que arrasta todos os polos) + um slider individual por polo
  ativo (com busca), cada um com o "SLA hoje" (P90 real da distância que aquele polo já atende dentro do
  prazo) como referência. Produtividade (Capital/Grande SP e Interior, até 40 OS/técnico/dia) e custo por
  técnico novo. Botão "Resetar Parâmetros" volta tudo ao valor base de jul/26.
- **Tooltip flutuante alternável** — ligado (padrão): passa o mouse e vê a prévia em tempo real; 1 clique
  seleciona/destaca, 2 cliques trava o painel completo (clicar fora ou ESC destrava). Desligado: sem hover
  contínuo, 1 clique já abre o painel completo — para quem prefere um mapa mais limpo.
- **Painel por localidade** — total de OS, volume Ógea/PagResolve, o polo PagResolve responsável (coluna
  da aba TEMPLATE) e quem capturou no cenário atual, sempre pelo nome completo do polo, nunca só o código.
  Traz um campo de exceção manual com busca preditiva (autocomplete: "Automático pelo raio", "Forçar Ógea
  (100%)" ou qualquer um dos 31 polos) — força aquela localidade para um polo específico independente do
  raio; sinalizado na exportação.
- **Modo Foco** — expande o mapa pra tela cheia, com um card flutuante mínimo (raio global, ou o raio de
  um polo específico ao clicar no marcador dele).
- **Detalhe por polo** — gaveta retrátil (não reduz a altura do mapa) com técnicos/CMU por polo e o botão
  "Exportar Cenário (.xlsx)".

## Regras de negócio do motor (`src/malha/assign.py`)

- Só participam os **31 polos com técnico ativo** hoje (aba CMU) — nenhum polo fantasma (sem equipe) entra
  no raio, nos sliders ou nas métricas.
- Cada local com volume Ógea é capturado (100%, regra binária) pelo polo mais próximo cujo raio o alcança;
  sem isso, o local mantém a proporção real de hoje — nunca vira "Território PagResolve" com 1% de share.
- **São Paulo capital**: dividida em 6 bairros (Campo Belo, Casa Verde, Itaquera, Vila Prudente, Vila
  Romana, Faria Lima), cada um só capturável pelo seu próprio polo (nunca um vizinho mais central). A
  demanda genérica da Ógea em "São Paulo" (sem bairro na BD) é repartida pelo **CEP real** em 6 zonas
  postais, cada uma vinculada a um desses polos — conferido exato contra a BD (soma 2.838 OS).
- Exceção manual do usuário (por localidade) vence qualquer regra automática acima.
- Técnicos sugeridos = teto(volume absorvido / produtividade mensal da região do polo). Novo CMU = (custo
  atual + técnicos novos × custo/técnico) / (volume base + absorvido) — sem alarme de prejuízo, só o número.
- Motor 100% numpy (sem solver): `preparar()` faz o trabalho caro uma vez; `simular()`/`simular_rapido()`
  respondem em ~10 ms por chamada — dá pra chamar a cada movimento de slider.

`src/malha/optimize.py` (MILP, PuLP/HiGHS) continua no repositório como ferramenta avançada/offline —
localização de instalações com capacidade, modos Simular/Otimizar — mas não é mais chamada pela tela
principal (nem desktop, nem Streamlit).

## Estrutura

```
src/malha/
  textnorm.py            normalização de texto/CEP/código de polo
  locais.py               nó de demanda: município, ou bairro/zona postal da capital
  ingest/                 leitura das abas BD, TEMPLATE, CMU e do cadastro de prestadores
  geo/                    municípios/polígonos IBGE, geocodificação (com cache), distância haversine
  build.py                pipeline completo: planilhas → parquets + relatório de qualidade
  baseline.py             KPIs atuais e defaults dos parâmetros (tudo derivado do dado)
  costs.py                 técnicos sugeridos e CMU do cenário
  assign.py                 motor determinístico (raio, território exclusivo, exceção manual)
  scenario.py, optimize.py  MILP de localização com capacidade (ferramenta avançada/offline)
  ml/                      raio de SLA, clustering de demanda órfã, score de hub (offline)
  viz/map.py                mapa Folium (usado só pela Streamlit)
  report.py                 export do cenário em Excel
desktop/
  main.py, api.py           janela nativa (PyWebView) + ponte com malha.assign
  static/                   index.html, app.js (MapLibre GL), style.css
app/Home.py                 mesma lógica, em Streamlit (navegador)
tests/                      pytest (normalização, custos, motor, locais, otimizador)
```

## Testes

```powershell
.venv\Scripts\pytest -q
```

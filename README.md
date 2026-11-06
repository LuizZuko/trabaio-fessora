# Data Warehouse & Analytics - Campo Real Energia ⚡

Projeto *end-to-end* de Engenharia de Dados, Governança e Analytics desenvolvido para a **Campo Real Energia**. O sistema realiza a ingestão de telemetria operacional, cotações do PLD (com mecanismo automático de fallback), dados meteorológicos da Open-Meteo, aplicação de suíte de auditoria em 7 dimensões de qualidade de dados e carga em um Data Warehouse Star Schema no PostgreSQL, alimentando painéis estratégicos no Tableau.

---

## 👥 Autores

* **Luiz Henrique Zukovski**
* **Alex David Backer**
* **Gabriel Caetano Nogueira**

---

## 📐 Arquitetura da Solução

```text
[ API CCEE (PLD) ] ────────► [ Contingência Fallback (403) ] ──┐
[ API Open-Meteo ]  ────────► [ Staging Open-Meteo ]          ├──► PostgreSQL (public) ──► [ Suite Qualidade (7D) ] ──► DW (dw_campo_real) ──► Tableau
[ Telemetria / ERP ] ───────► [ Tabelas Operacionais ]        ──┘
```

---

## 📁 Estrutura do Repositório

```text
.
├── sql/
│   └── dw_campo_real.sql             # DDL do Star Schema, índices e restrições
├── src/
│   ├── config.py                     # Configuração e string de conexão do PostgreSQL
│   ├── extracao_ccee.py              # Ingestão de PLD com fallback sazonal parametrizado
│   ├── extracao_openmeteo.py         # Extração de dados climáticos via API Open-Meteo
│   ├── qualidade.py                  # Suíte de auditoria automatizada (7 dimensões)
│   └── carga_dw.py                   # Transformação e carga dimensional (Star Schema)
├── relatorio_tecnico_dw_campo_real.pdf # Relatório técnico executivo
├── Dashboard_Campo_Real.twbx         # Pasta de trabalho empacotada do Tableau
├── requirements.txt                  # Dependências Python do ambiente virtual
└── README.md                         # Documentação principal do projeto
```

---

## 🛠️ Tecnologias e Bibliotecas

* **Linguagem:** Python 3.12 (`venv`)
* **Banco de Dados:** PostgreSQL 16
* **Drivers & ORM:** `SQLAlchemy`, `psycopg2-binary`
* **Manipulação de Dados:** `pandas`, `numpy`
* **Visualização:** Tableau Desktop

---

## 🔍 Suíte de Auditoria de Qualidade (7 Dimensões)

O script `src/qualidade.py` executa validações rigorosas antes de autorizar a carga no Data Warehouse. Os resultados de cada execução são persistidos na tabela `public.metrica_qualidade`.

| Dimensão | Regra Auditada | Alvo | Tratamento ETL |
| :--- | :--- | :--- | :--- |
| **Completude** | Not Null em `energia_mwh` e `id_usina` | `medicao_geracao` | Nulos mapeados para Membro Desconhecido (`sk = -1`). |
| **Unicidade** | Chave composta `(id_usina, data_hora)` | `medicao_geracao` | Deduplicação por janela temporal via `ROW_NUMBER()`. |
| **Validade** | Coordenadas geo e teto/piso do PLD | `usina` / `pld_horario` | Ajuste de limites e normalização de vírgulas e tipos. |
| **Consistência** | `fim_parada > inicio_parada` | `parada_usina` | Registros inconsistentes sinalizados no log de auditoria. |
| **Acurácia** | `energia_mwh <= potencia_mw` | `medicao_geracao` | Correção de escala de ordens de grandeza (kWh -> MWh). |
| **Integridade** | Referência em dimensões pai | `medicao_geracao` | FKs órfãs direcionadas para membro desconhecido padrão. |
| **Atualidade** | SLA de latência na telemetria | `medicao_geracao` | Monitoramento de defasagem do envio (< 48h). |

---

## 📊 Modelo Dimensional (Star Schema)

O Data Warehouse reside no schema isolado **`dw_campo_real`**:

### Tabelas de Dimensão
* **`dim_tempo` (Grão Horário):** 8.760 horas de 2025 com atributos de calendário, estações do ano, feriados e patamares de carga (Pesada, Média, Leve).
* **`dim_usina`:** Cadastro master com suporte a histórico **SCD Tipo 2** (`data_inicio_scd`, `data_fim_scd`, `atual_scd`).
* **`dim_submercado`:** Submercados do SIN (SE/CO, S, NE, N) + Membro Desconhecido (`NA`).
* **`dim_fonte`:** Matrizes de geração (Solar, Eólica, Hídrica, Térmica, Biomassa).

### Tabelas Fato
* **`fato_geracao`:** Fato principal no grão usina x hora. Armazena `energia_gerada_mwh`, `disponibilidade_mw`, `fator_capacidade_pct`, `receita_valorada_rs`, `energia_perdida_mwh` e `receita_perdida_rs`.
* **`fato_pld`:** Histórico de preços horários por submercado e origem do dado (`CCEE_API` vs. `SIMULADO_FALLBACK`).
* **`fato_clima`:** Dados meteorológicos por usina x hora (temperatura, vento, chuva e radiação).

---

## 🚀 Como Executar o Projeto

### 1. Pré-requisitos e Configuração do Ambiente

```powershell
# Criar e ativar o ambiente virtual (Windows)
python -m venv venv
.\venv\Scripts\activate

# Instalar dependências
pip install -r requirements.txt
```

### 2. Configurar Variáveis de Conexão

Edite o arquivo `src/config.py` com suas credenciais do PostgreSQL local:

```python
class Config:
    DB_HOST = "localhost"
    DB_PORT = "5432"
    DB_NAME = "campo_real_energia"
    DB_USER = "postgres"
    DB_PASS = "sua_senha"
```

### 3. Execução da Pipeline ETL

Execute a sequência dos scripts no terminal:

```powershell
# 1. Extração do PLD CCEE (com mecanismo automático de fallback)
python src/extracao_ccee.py

# 2. Extração dos Dados Climáticos (Open-Meteo)
python src/extracao_openmeteo.py

# 3. Execução da Suíte de Auditoria de Qualidade
python src/qualidade.py

# 4. Transformação e Carga no Data Warehouse (dw_campo_real)
python src/carga_dw.py
```

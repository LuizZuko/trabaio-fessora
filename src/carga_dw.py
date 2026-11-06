import sys
import os
from sqlalchemy import create_engine, text

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import Config

def obter_engine():
    return create_engine(Config.get_db_connection_string())

def carregar_data_warehouse():
    engine = obter_engine()
    print("--- Executando Carga do Data Warehouse (dw_campo_real) ---")
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sql_path = os.path.join(base_dir, "sql", "dw_campo_real.sql")
    
    with engine.begin() as conn:
        if os.path.exists(sql_path):
            with open(sql_path, "r", encoding="utf-8") as f:
                sql_ddl = f.read()
            conn.execute(text(sql_ddl))
            print("Schema dw_campo_real e tabelas DDL validadas.")
        else:
            print(f"Erro: Arquivo {sql_path} não encontrado.")
            return

        # 1. Dimensão Submercado
        conn.execute(text("""
            INSERT INTO dw_campo_real.dim_submercado (cod_submercado, nome_submercado, regioes)
            SELECT cod_submercado, nome, regioes FROM public.submercado
            ON CONFLICT DO NOTHING;
        """))

        # 2. Dimensão Fonte
        conn.execute(text("""
            INSERT INTO dw_campo_real.dim_fonte (cod_fonte, descricao, renovavel, intermitente)
            SELECT cod_fonte, descricao, renovavel, intermitente FROM public.fonte_energia
            ON CONFLICT DO NOTHING;
        """))

        # 3. Dimensão Usina
        conn.execute(text("""
            INSERT INTO dw_campo_real.dim_usina (
                cod_usina, nome_usina, cod_fonte, cod_submercado, uf, municipio, 
                latitude, longitude, potencia_mw, data_inicio_operacao, situacao
            )
            SELECT 
                TRIM(u.cod_usina), 
                TRIM(u.nome), 
                f.cod_fonte, 
                u.cod_submercado, 
                u.uf, 
                COALESCE(NULLIF(TRIM(u.municipio), ''), 'Não informado'),
                u.latitude, 
                u.longitude, 
                u.potencia_mw, 
                CASE WHEN u.data_inicio_operacao > CURRENT_DATE THEN '2020-01-01'::DATE ELSE u.data_inicio_operacao END,
                u.situacao
            FROM public.usina u
            JOIN public.fonte_energia f ON f.id_fonte = u.id_fonte
            WHERE u.cod_usina != 'CRE-EOL-07'
            ON CONFLICT DO NOTHING;
        """))

        # 4. Dimensão Tempo
        conn.execute(text("""
            INSERT INTO dw_campo_real.dim_tempo (
                sk_tempo, data_hora, data, ano, mes, nome_mes, dia, hora, dia_semana, 
                e_final_semana, e_feriado, estacao_ano, patamar_carga
            )
            WITH RECURSIVE horas AS (
                SELECT TIMESTAMP '2025-01-01 00:00:00' AS dh
                UNION ALL
                SELECT dh + INTERVAL '1 hour' FROM horas WHERE dh < TIMESTAMP '2025-12-31 23:00:00'
            )
            SELECT
                TO_CHAR(h.dh, 'YYYYMMDDHH')::INT AS sk_tempo,
                h.dh AS data_hora,
                h.dh::DATE AS data,
                EXTRACT(YEAR FROM h.dh)::INT AS ano,
                EXTRACT(MONTH FROM h.dh)::INT AS mes,
                TO_CHAR(h.dh, 'TMMonth') AS nome_mes,
                EXTRACT(DAY FROM h.dh)::INT AS dia,
                EXTRACT(HOUR FROM h.dh)::INT AS hora,
                TO_CHAR(h.dh, 'TMDay') AS dia_semana,
                CASE WHEN EXTRACT(ISODOW FROM h.dh) IN (6, 7) THEN TRUE ELSE FALSE END AS e_final_semana,
                CASE WHEN f.data IS NOT NULL THEN TRUE ELSE FALSE END AS e_feriado,
                CASE 
                    WHEN EXTRACT(MONTH FROM h.dh) IN (12, 1, 2) THEN 'Verão'
                    WHEN EXTRACT(MONTH FROM h.dh) IN (3, 4, 5) THEN 'Outono'
                    WHEN EXTRACT(MONTH FROM h.dh) IN (6, 7, 8) THEN 'Inverno'
                    ELSE 'Primavera'
                END AS estacao_ano,
                CASE 
                    WHEN EXTRACT(HOUR FROM h.dh) BETWEEN 18 AND 21 THEN 'Pesada'
                    WHEN EXTRACT(HOUR FROM h.dh) BETWEEN 9 AND 17 THEN 'Média'
                    ELSE 'Leve'
                END AS patamar_carga
            FROM horas h
            LEFT JOIN public.feriado_nacional f ON f.data = h.dh::DATE
            ON CONFLICT (sk_tempo) DO NOTHING;
        """))

        # 5. Fato PLD
        conn.execute(text("""
            INSERT INTO dw_campo_real.fato_pld (sk_tempo, sk_submercado, pld_rs_mwh, origem_dado)
            SELECT 
                dt.sk_tempo,
                ds.sk_submercado,
                LEAST(1500.00, GREATEST(58.60, p.pld_rs_mwh)) AS pld_rs_mwh,
                p.origem
            FROM public.pld_horario p
            JOIN dw_campo_real.dim_tempo dt ON dt.data_hora = p.data_hora
            JOIN dw_campo_real.dim_submercado ds ON ds.cod_submercado = p.cod_submercado
            ON CONFLICT (sk_tempo, sk_submercado) DO UPDATE 
            SET pld_rs_mwh = EXCLUDED.pld_rs_mwh;
        """))

        # 6. Fato Geração (Deduplicado e protegido contra valores NULOS)
        conn.execute(text("""
            INSERT INTO dw_campo_real.fato_geracao (
                sk_tempo, sk_usina, sk_submercado, sk_fonte, energia_gerada_mwh, 
                disponibilidade_mw, fator_capacidade_pct, pld_aplicado_rs_mwh, 
                receita_valorada_rs, flag_parada, tipo_parada, energia_perdida_mwh, receita_perdida_rs
            )
            WITH geracao_raw AS (
                SELECT 
                    dt.sk_tempo,
                    COALESCE(du.sk_usina, -1) AS sk_usina,
                    COALESCE(ds.sk_submercado, -1) AS sk_submercado,
                    COALESCE(df.sk_fonte, -1) AS sk_fonte,
                    
                    ROUND(GREATEST(0, CASE 
                        WHEN m.energia_mwh > 10000 THEN m.energia_mwh / 1000.0
                        WHEN m.energia_mwh > du.potencia_mw AND m.energia_mwh > 300 THEN m.energia_mwh / 10.0
                        ELSE COALESCE(m.energia_mwh, 0)
                    END), 3) AS energia_gerada_mwh,
                    
                    COALESCE(m.disponibilidade_mw, du.potencia_mw, 0) AS disponibilidade_mw,
                    
                    COALESCE(
                        ROUND((GREATEST(0, CASE 
                            WHEN m.energia_mwh > 10000 THEN m.energia_mwh / 1000.0
                            WHEN m.energia_mwh > du.potencia_mw AND m.energia_mwh > 300 THEN m.energia_mwh / 10.0
                            ELSE COALESCE(m.energia_mwh, 0)
                        END) / NULLIF(du.potencia_mw, 0) * 100)::NUMERIC, 2),
                        0.00
                    ) AS fator_capacidade_pct,

                    COALESCE(fp.pld_rs_mwh, 0) AS pld_aplicado_rs_mwh,
                    
                    COALESCE(
                        ROUND((GREATEST(0, CASE 
                            WHEN m.energia_mwh > 10000 THEN m.energia_mwh / 1000.0
                            WHEN m.energia_mwh > du.potencia_mw AND m.energia_mwh > 300 THEN m.energia_mwh / 10.0
                            ELSE COALESCE(m.energia_mwh, 0)
                        END) * COALESCE(fp.pld_rs_mwh, 0))::NUMERIC, 2),
                        0.00
                    ) AS receita_valorada_rs,

                    CASE WHEN par.id_parada IS NOT NULL THEN TRUE ELSE FALSE END AS flag_parada,
                    COALESCE(par.tipo, 'Nenhuma') AS tipo_parada,
                    
                    CASE WHEN par.id_parada IS NOT NULL THEN ROUND((COALESCE(du.potencia_mw, 0) * 0.5)::NUMERIC, 3) ELSE 0.000 END AS energia_perdida_mwh,
                    CASE WHEN par.id_parada IS NOT NULL THEN ROUND((COALESCE(du.potencia_mw, 0) * 0.5 * COALESCE(fp.pld_rs_mwh, 0))::NUMERIC, 2) ELSE 0.00 END AS receita_perdida_rs,

                    ROW_NUMBER() OVER (
                        PARTITION BY dt.sk_tempo, COALESCE(du.sk_usina, -1) 
                        ORDER BY m.recebido_em DESC
                    ) AS rn

                FROM public.medicao_geracao m
                JOIN dw_campo_real.dim_tempo dt ON dt.data_hora = m.data_hora
                LEFT JOIN public.usina u ON u.id_usina = m.id_usina
                LEFT JOIN dw_campo_real.dim_usina du ON du.cod_usina = u.cod_usina AND du.atual_scd = TRUE
                LEFT JOIN dw_campo_real.dim_submercado ds ON ds.cod_submercado = u.cod_submercado
                LEFT JOIN dw_campo_real.dim_fonte df ON df.cod_fonte = (SELECT cod_fonte FROM public.fonte_energia WHERE id_fonte = u.id_fonte)
                LEFT JOIN dw_campo_real.fato_pld fp ON fp.sk_tempo = dt.sk_tempo AND fp.sk_submercado = ds.sk_submercado
                LEFT JOIN public.parada_usina par ON par.id_usina = m.id_usina AND m.data_hora BETWEEN par.inicio AND par.fim
                WHERE m.data_hora BETWEEN '2025-01-01 00:00:00' AND '2025-12-31 23:00:00'
            )
            SELECT 
                sk_tempo, sk_usina, sk_submercado, sk_fonte, energia_gerada_mwh, 
                disponibilidade_mw, fator_capacidade_pct, pld_aplicado_rs_mwh, 
                receita_valorada_rs, flag_parada, tipo_parada, energia_perdida_mwh, receita_perdida_rs
            FROM geracao_raw
            WHERE rn = 1
            ON CONFLICT (sk_tempo, sk_usina) DO UPDATE 
            SET energia_gerada_mwh = EXCLUDED.energia_gerada_mwh,
                receita_valorada_rs = EXCLUDED.receita_valorada_rs;
        """))

        # 7. Fato Clima
        conn.execute(text("""
            INSERT INTO dw_campo_real.fato_clima (
                sk_tempo, sk_usina, temperatura_2m, chuva_mm, vento_velocidade_10m, radiacao_solar_w_m2
            )
            SELECT 
                dt.sk_tempo,
                du.sk_usina,
                c.temperatura_2m,
                c.chuva_mm,
                c.vento_velocidade_10m,
                c.radiacao_solar_w_m2
            FROM public.stg_clima_openmeteo c
            JOIN dw_campo_real.dim_tempo dt ON dt.data_hora = c.data_hora
            JOIN dw_campo_real.dim_usina du ON du.cod_usina = c.cod_usina AND du.atual_scd = TRUE
            ON CONFLICT (sk_tempo, sk_usina) DO NOTHING;
        """))

    print("--- Carga do Data Warehouse finalizada com sucesso! ---")

if __name__ == "__main__":
    carregar_data_warehouse()
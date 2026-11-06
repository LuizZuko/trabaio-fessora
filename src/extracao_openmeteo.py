import sys
import os
import time
import pandas as pd
import requests
from sqlalchemy import create_engine, text

# Garante que o diretório src está no caminho de importação do Python
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import Config

def obter_engine():
    return create_engine(Config.get_db_connection_string())

def criar_tabela_clima_raw(engine):
    sql = text("""
        CREATE TABLE IF NOT EXISTS stg_clima_openmeteo (
            id_usina INT,
            cod_usina VARCHAR(20),
            data_hora TIMESTAMP,
            temperatura_2m NUMERIC(5,2),
            chuva_mm NUMERIC(6,2),
            vento_velocidade_10m NUMERIC(5,2),
            radiacao_solar_w_m2 NUMERIC(7,2),
            origem VARCHAR(50),
            carregado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id_usina, data_hora)
        );
    """)
    with engine.begin() as conn:
        conn.execute(sql)

def buscar_usinas(engine):
    query = text("SELECT id_usina, cod_usina, nome, latitude, longitude FROM usina;")
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    return df

def extrair_open_meteo_usina(latitude, longitude):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "hourly": "temperature_2m,rain,wind_speed_10m,direct_normal_irradiance",
        "timezone": "America/Sao_Paulo"
    }
    
    for tentativa in range(1, 4):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                dados = r.json().get("hourly", {})
                df = pd.DataFrame({
                    "data_hora": pd.to_datetime(dados.get("time")),
                    "temperatura_2m": dados.get("temperature_2m"),
                    "chuva_mm": dados.get("rain"),
                    "vento_velocidade_10m": dados.get("wind_speed_10m"),
                    "radiacao_solar_w_m2": dados.get("direct_normal_irradiance")
                })
                return df
        except Exception as e:
            print(f"Tentativa {tentativa} falhou: {e}")
        time.sleep(2)
    return pd.DataFrame()

def executar_pipeline_clima():
    engine = obter_engine()
    criar_tabela_clima_raw(engine)
    usinas = buscar_usinas(engine)
    
    total_linhas = 0
    print("--- Iniciando Extração Open-Meteo ---")
    
    for idx, usina in usinas.iterrows():
        print(f"Extraindo clima para usina: {usina['cod_usina']} ({usina['nome']})...")
        df_clima = extrair_open_meteo_usina(usina["latitude"], usina["longitude"])
        
        if not df_clima.empty:
            df_clima["id_usina"] = usina["id_usina"]
            df_clima["cod_usina"] = usina["cod_usina"]
            df_clima["origem"] = "API_OPEN_METEO"
            
            with engine.begin() as conn:
                df_clima.to_sql("stg_clima_openmeteo", conn, if_exists="append", index=False)
            
            total_linhas += len(df_clima)
            print(f"-> {len(df_clima)} registros gravados para {usina['cod_usina']}.")
        time.sleep(1)
        
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO log_carga (tabela, arquivo, linhas, status, observacao)
            VALUES ('stg_clima_openmeteo', 'API_OPEN_METEO_HISTORICO', :linhas, 'SUCESSO', 'Carga de clima historico Open-Meteo 2025');
        """), {"linhas": total_linhas})
        
    print(f"Carga concluída! Total de linhas de clima gravadas: {total_linhas}")

if __name__ == "__main__":
    executar_pipeline_clima()
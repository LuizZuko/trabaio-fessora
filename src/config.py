import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "campo_real_energia")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS", "postgres")
    
    CCEE_URL = os.getenv("CCEE_URL", "https://dadosabertos.ccee.org.br/api/3/action/datastore_search")
    CCEE_RES_ID_2025 = os.getenv("CCEE_RES_ID_2025", "pld_horario_2025")
    CCEE_RES_ID_2026 = os.getenv("CCEE_RES_ID_2026", "pld_horario_2026")

    @staticmethod
    def get_db_connection_string():
        return f"postgresql+psycopg2://{Config.DB_USER}:{Config.DB_PASS}@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}"
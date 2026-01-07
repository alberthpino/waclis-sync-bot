import os
import re
import time
import requests
import psycopg2
from openai import OpenAI

# DEBUG: Ver qué variables están disponibles
print("=== DEBUG: Variables de entorno ===")
print(f"OPENAI_API_KEY existe: {bool(os.getenv('OPENAI_API_KEY'))}")
print(f"DB_NAME: {os.getenv('DB_NAME')}")
print(f"DB_HOST: {os.getenv('DB_HOST')}")
print("===================================")

def get_env_var(key):
    """Obtiene una variable de entorno y lanza error si no existe"""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"ERROR: Variable de entorno {key} no encontrada")
    return value.strip()

def conseguir_llave():
    # Intento 1: Variable de entorno directa
    llave = os.getenv("OPENAI_API_KEY")
    if llave:
        return llave.strip()

    # Intento 2: Leer el archivo .env manualmente
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if "=" in line and "OPENAI_API_KEY" in line:
                    parts = line.split("=", 1)
                    if len(parts) > 1:
                        return parts[1].replace('"', '').replace("'", "").strip()
    return None

# Verificar API key primero
api_key = conseguir_llave()
if not api_key:
    raise ValueError("ERROR FATAL: No se detectó la OPENAI_API_KEY. Revisa la pestaña Entorno en Easypanel.")

client = OpenAI(api_key=api_key)

# Configuración de base de datos
DB_PARAMS = {
    "dbname": get_env_var("DB_NAME"),
    "user": get_env_var("DB_USER"),
    "password": get_env_var("DB_PASS"),
    "host": get_env_var("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432")  # Valor por defecto si no existe
}

def limpiar_html(raw_html):
    if not raw_html: 
        return ""
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html).replace('&nbsp;', ' ').strip()

def obtener_embedding(texto):
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texto
    )
    return response.data[0].embedding

def procesar():
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        
        # Obtener tiendas
        tiendas = requests.get("https://nextiendas.com/stores/waclis/products").json()

        for tienda in tiendas:
            print(f"Tienda: {tienda['name']}")
            productos = requests.get(tienda['url']).json()

            for prod in productos:
                p_id = str(prod['id'])
                nombre = prod.get('name', 'Sin nombre')
                # Creamos una versión legible para la IA
                texto_ia = f"Producto: {nombre}. SKU: {prod.get('sku')}. Precio: {prod.get('price')} {prod.get('currency')}. Stock: {prod.get('stock')}."
                
                vector = obtener_embedding(texto_ia)

                # Upsert basado en product_id
                cur.execute("SELECT id FROM captain_assistant_responses WHERE product_id = %s", (p_id,))
                if cur.fetchone():
                    query = "UPDATE captain_assistant_responses SET content = %s, content_vector = %s, updated_at = NOW() WHERE product_id = %s"
                    cur.execute(query, (texto_ia, vector, p_id))
                else:
                    query = """INSERT INTO captain_assistant_responses 
                               (content, assistant_id, account_id, content_vector, product_id, store_id, created_at, updated_at) 
                               VALUES (%s, 1, 1, %s, %s, %s, NOW(), NOW())"""
                    cur.execute(query, (texto_ia, vector, p_id, str(tienda['id'])))
            
            conn.commit()
        
        cur.close()
        conn.close()
        print("Sincronización finalizada con éxito.")
    except Exception as e:
        print(f"Error: {e}")
        raise  # Re-lanzar el error para debugging

if __name__ == "__main__":
    procesar()
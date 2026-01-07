import os
import re
import json
import time
import requests
import psycopg2
from openai import OpenAI
# from dotenv import load_dotenv

# Cargar variables de entorno
# load_dotenv()

# Configuración
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("ERROR: OPENAI_API_KEY no encontrada en variables de entorno")

client = OpenAI(api_key=OPENAI_API_KEY)

DB_PARAMS = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASS"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432")
}

# Validar configuración de BD
for key, value in DB_PARAMS.items():
    if not value:
        raise ValueError(f"ERROR: {key} no encontrado en variables de entorno")

# URLs
STORES_URL = "https://entornoqa.com.ar/apisgenerales/tiendas-activas-suscripcion-wia?token=c29390ba52d8d24931adf4654772341a"

def limpiar_html(raw_html):
    """Elimina etiquetas HTML y limpia el texto"""
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    texto = re.sub(cleanr, '', raw_html)
    # Reemplazar entidades HTML comunes
    replacements = {
        '&nbsp;': ' ',
        '&aacute;': 'á',
        '&eacute;': 'é',
        '&iacute;': 'í',
        '&oacute;': 'ó',
        '&uacute;': 'ú',
        '&ntilde;': 'ñ',
        '&Aacute;': 'Á',
        '&Eacute;': 'É',
        '&Iacute;': 'Í',
        '&Oacute;': 'Ó',
        '&Uacute;': 'Ú',
        '&Ntilde;': 'Ñ',
        '&amp;': '&',
        '&lt;': '<',
        '&gt;': '>',
        '&quot;': '"',
        '&#039;': "'",
        '\\/': '/'
    }
    for old, new in replacements.items():
        texto = texto.replace(old, new)
    return texto.strip()

def obtener_embedding(texto):
    """Genera embedding usando OpenAI (modelo más barato)"""
    try:
        # Limitar longitud para ahorrar tokens
        texto_truncado = texto[:6000]
        
        response = client.embeddings.create(
            model="text-embedding-3-small",  # $0.02 por 1M tokens
            input=texto_truncado
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"❌ Error al generar embedding: {e}")
        return None

def crear_texto_para_embedding(producto):
    """Crea un texto optimizado y conciso para búsqueda semántica"""
    desc_limpia = limpiar_html(producto.get('description', ''))
    
    # Información básica
    nombre = producto.get('name', 'Sin nombre')
    sku = producto.get('sku', 'N/A')
    precio = producto.get('price', 0)
    moneda = producto.get('currency', 'ARS')
    stock_total = producto.get('stock', 0)
    
    # Categorías
    categorias = [cat['name'] for cat in producto.get('categories', [])]
    cats_texto = ', '.join(set(categorias)) if categorias else 'Sin categoría'
    
    # Variantes (solo si existen y son relevantes)
    variantes_info = []
    for var in producto.get('variants', [])[:5]:  # Máximo 5 variantes
        attrs = var.get('attributes', [])
        color = next((a['value'] for a in attrs if a['name'] == 'Color'), None)
        stock_var = var.get('stock', 0)
        precio_var = var.get('price', precio)
        
        if color:
            variantes_info.append(f"{color} ({stock_var} unid, ${precio_var})")
    
    # Construir texto optimizado
    texto_partes = [
        f"Producto: {nombre}",
        f"SKU: {sku}",
        f"Precio: ${precio} {moneda}",
        f"Stock disponible: {stock_total} unidades"
    ]
    
    if desc_limpia:
        texto_partes.append(f"Descripción: {desc_limpia[:300]}")  # Limitar descripción
    
    if categorias:
        texto_partes.append(f"Categorías: {cats_texto}")
    
    if variantes_info:
        texto_partes.append(f"Variantes: {', '.join(variantes_info)}")
    
    # Info adicional
    min_qty = producto.get('minimum_recommended_quantity')
    if min_qty:
        texto_partes.append(f"Cantidad mínima: {min_qty}")
    
    prod_days = producto.get('production_days')
    if prod_days:
        texto_partes.append(f"Días de producción: {prod_days}")
    
    dims = producto.get('dimensions', {})
    if dims and any(dims.values()):
        texto_partes.append(
            f"Dimensiones: {dims.get('length', 0)}x{dims.get('width', 0)}x{dims.get('height', 0)} cm"
        )
    
    peso = producto.get('weight')
    if peso:
        texto_partes.append(f"Peso: {peso}g")
    
    return '\n'.join(texto_partes)

def upsert_producto(cursor, producto, store_id):
    """Inserta o actualiza un producto en captain_assistant_responses"""
    product_id = str(producto['id'])
    product_name = producto.get('name', 'Sin nombre')
    
    try:
        # Crear el contenido para embedding
        texto_embedding = crear_texto_para_embedding(producto)
        
        # Generar embedding
        vector = obtener_embedding(texto_embedding)
        if not vector:
            print(f"  ❌ Fallo en embedding para: {product_name[:40]}")
            return False
        
        # Guardar JSON completo como content
        content_json = json.dumps(producto, ensure_ascii=False)
        
        # Verificar si el producto ya existe
        cursor.execute(
            "SELECT id FROM captain_assistant_responses WHERE product_id = %s",
            (product_id,)
        )
        existe = cursor.fetchone()
        
        if existe:
            # UPDATE
            query = """
                UPDATE captain_assistant_responses 
                SET content = %s, 
                    content_vector = %s, 
                    store_id = %s,
                    updated_at = NOW() 
                WHERE product_id = %s
            """
            cursor.execute(query, (content_json, vector, str(store_id), product_id))
            print(f"  ✅ Actualizado: {product_name[:50]}")
        else:
            # INSERT
            query = """
                INSERT INTO captain_assistant_responses 
                (content, assistant_id, account_id, content_vector, product_id, store_id, created_at, updated_at) 
                VALUES (%s, 1, 1, %s, %s, %s, NOW(), NOW())
            """
            cursor.execute(query, (content_json, vector, product_id, str(store_id)))
            print(f"  ➕ Insertado: {product_name[:50]}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error procesando {product_name[:40]}: {str(e)[:100]}")
        return False

def sincronizar():
    """Proceso principal de sincronización"""
    inicio = time.time()
    
    print("\n" + "=" * 70)
    print("🚀 INICIANDO SINCRONIZACIÓN DE PRODUCTOS")
    print("=" * 70)
    print(f"⏰ Inicio: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")
    
    conn = None
    cursor = None
    
    try:
        # Obtener lista de tiendas
        print(f"📡 Consultando tiendas desde: {STORES_URL}")
        response = requests.get(STORES_URL, timeout=30)
        response.raise_for_status()
        tiendas = response.json()
        print(f"✅ Tiendas encontradas: {len(tiendas)}\n")
        
        # Conectar a la base de datos
        print(f"🔌 Conectando a base de datos: {DB_PARAMS['host']}")
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        print("✅ Conexión establecida\n")
        
        total_procesados = 0
        total_exitosos = 0
        total_fallidos = 0
        
        # Procesar cada tienda
        for idx_tienda, tienda in enumerate(tiendas, 1):
            store_id = tienda['id_store']
            store_name = tienda['name']
            products_url = tienda['productos_json_url']
            
            print("=" * 70)
            print(f"🏪 [{idx_tienda}/{len(tiendas)}] TIENDA: {store_name} (ID: {store_id})")
            print("=" * 70)
            
            try:
                # Obtener productos de la tienda
                print(f"📡 Consultando productos...")
                prod_response = requests.get(products_url, timeout=30)
                prod_response.raise_for_status()
                productos = prod_response.json()
                print(f"✅ Productos encontrados: {len(productos)}\n")
                
                exitosos_tienda = 0
                fallidos_tienda = 0
                
                # Procesar cada producto
                for idx_prod, producto in enumerate(productos, 1):
                    print(f"[{idx_prod}/{len(productos)}]", end=" ")
                    total_procesados += 1
                    
                    if upsert_producto(cursor, producto, store_id):
                        total_exitosos += 1
                        exitosos_tienda += 1
                    else:
                        total_fallidos += 1
                        fallidos_tienda += 1
                    
                    # Commit cada 20 productos
                    if idx_prod % 20 == 0:
                        conn.commit()
                        print(f"  💾 Guardado intermedio ({idx_prod}/{len(productos)})")
                
                # Commit final de la tienda
                conn.commit()
                
                print(f"\n✅ Tienda completada: {exitosos_tienda} exitosos, {fallidos_tienda} fallidos\n")
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Error de conexión con tienda {store_name}: {e}\n")
                continue
            except Exception as e:
                print(f"❌ Error procesando tienda {store_name}: {e}\n")
                if conn:
                    conn.rollback()
                continue
        
        # Resumen final
        duracion = time.time() - inicio
        minutos = int(duracion // 60)
        segundos = int(duracion % 60)
        
        print("\n" + "=" * 70)
        print("✅ SINCRONIZACIÓN COMPLETADA")
        print("=" * 70)
        print(f"⏰ Duración: {minutos}m {segundos}s")
        print(f"📊 Total procesados: {total_procesados}")
        print(f"✅ Exitosos: {total_exitosos} ({(total_exitosos/total_procesados*100):.1f}%)")
        print(f"❌ Fallidos: {total_fallidos} ({(total_fallidos/total_procesados*100):.1f}%)")
        print("=" * 70 + "\n")
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ ERROR DE CONEXIÓN: {e}\n")
        raise
    except psycopg2.Error as e:
        print(f"\n❌ ERROR DE BASE DE DATOS: {e}\n")
        raise
    except Exception as e:
        print(f"\n❌ ERROR FATAL: {e}\n")
        raise
    finally:
        # Cerrar conexiones
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            print("🔌 Conexión a BD cerrada\n")

if __name__ == "__main__":
    print("\n" + "🤖 " * 20)
    print("SERVICIO DE SINCRONIZACIÓN NEXTIENDAS → CHATWOOT")
    print("🤖 " * 20 + "\n")
    
    ciclo = 0
    
    while True:
        try:
            ciclo += 1
            print(f"\n{'🔄' * 35}")
            print(f"CICLO #{ciclo}")
            print(f"{'🔄' * 35}\n")
            
            sincronizar()
            
            proxima_ejecucion = time.time() + 21600
            print(f"⏰ Esperando 6 horas...")
            print(f"💤 Próxima sincronización: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(proxima_ejecucion))}")
            print(f"{'─' * 70}\n")
            
            time.sleep(21600)  # 6 horas
            
        except KeyboardInterrupt:
            print("\n\n🛑 SERVICIO DETENIDO POR EL USUARIO\n")
            break
        except Exception as e:
            print(f"\n❌ ERROR EN CICLO #{ciclo}: {e}")
            print("⏰ Reintentando en 5 minutos...\n")
            time.sleep(300)  # 5 minutos
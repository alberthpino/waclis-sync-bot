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
STORES_URL = "https://nextiendas.com/apisgenerales/tiendas-activas-suscripcion-wia?token=c29390ba52d8d24931adf4654772341a"

def crear_slug(texto):
    """Crea un slug URL-friendly a partir de un texto"""
    if not texto:
        return ""
    
    # Convertir a minúsculas
    slug = texto.lower()
    
    # Reemplazar caracteres especiales y acentos
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u',
        'ñ': 'n', 'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        'ä': 'a', 'ë': 'e', 'ï': 'i', 'ö': 'o', 'â': 'a', 'ê': 'e',
        'î': 'i', 'ô': 'o', 'û': 'u', 'ã': 'a', 'õ': 'o', 'ç': 'c'
    }
    
    for old, new in replacements.items():
        slug = slug.replace(old, new)
    
    # Eliminar caracteres no alfanuméricos excepto espacios y guiones
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    
    # Reemplazar múltiples espacios o guiones por uno solo
    slug = re.sub(r'[\s-]+', '-', slug)
    
    # Eliminar guiones al inicio y final
    slug = slug.strip('-')
    
    return slug

def generar_product_url(dominio, product_id, product_name):
    """Genera la URL completa del producto"""
    # Asegurar que el dominio no termine con /
    dominio = dominio.rstrip('/')
    
    # Crear el slug del nombre del producto
    slug = crear_slug(product_name)
    
    # Si el slug está vacío, usar solo el ID
    if not slug:
        slug = f"producto-{product_id}"
    
    # Construir la URL
    product_url = f"{dominio}/productos/{product_id}/{slug}"
    
    return product_url

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

def crear_answer_legible(producto, product_url):
    """Crea un texto legible y estructurado para el campo answer"""
    
    # Información básica
    answer_partes = [
        f"📦 INFORMACIÓN DEL PRODUCTO",
        f"",
        f"Nombre: {producto.get('name', 'Sin nombre')}",
        f"SKU: {producto.get('sku', 'N/A')}",
        f"ID Producto: {producto.get('id')}",
    ]
    
    # Agregar URL del producto si existe
    if product_url:
        answer_partes.extend([
            f"",
            f"🔗 VER FICHA DEL PRODUCTO",
            f"{product_url}"
        ])
    
    answer_partes.extend([
        f"",
        f"💰 PRECIO Y STOCK",
        f"Precio: ${producto.get('price', 0)} {producto.get('currency', 'ARS')}",
        f"Stock Total: {producto.get('stock', 0)} unidades",
    ])
    
    # Descripción
    desc = limpiar_html(producto.get('description', ''))
    if desc:
        answer_partes.extend([
            f"",
            f"📝 DESCRIPCIÓN",
            desc
        ])
    
    # Categorías
    categorias = producto.get('categories', [])
    if categorias:
        cats = ', '.join(set([cat['name'] for cat in categorias]))
        answer_partes.extend([
            f"",
            f"🏷️ CATEGORÍAS",
            cats
        ])
    
    # Variantes
    variantes = producto.get('variants', [])
    if variantes:
        answer_partes.extend([
            f"",
            f"🎨 VARIANTES DISPONIBLES ({len(variantes)})"
        ])
        for i, var in enumerate(variantes, 1):
            attrs = var.get('attributes', [])
            color = next((a['value'] for a in attrs if a['name'] == 'Color'), 'Sin especificar')
            answer_partes.append(
                f"  {i}. {color} - Stock: {var.get('stock', 0)} unid - Precio: ${var.get('price', 0)}"
            )
    
    # Info adicional
    min_qty = producto.get('minimum_recommended_quantity')
    prod_days = producto.get('production_days')
    peso = producto.get('weight')
    dims = producto.get('dimensions', {})
    
    if any([min_qty, prod_days, peso, dims.get('length')]):
        answer_partes.extend([f"", f"ℹ️ INFORMACIÓN ADICIONAL"])
        if min_qty:
            answer_partes.append(f"Cantidad mínima recomendada: {min_qty}")
        if prod_days:
            answer_partes.append(f"Días de producción: {prod_days}")
        if peso:
            answer_partes.append(f"Peso: {peso}g")
        if dims.get('length'):
            answer_partes.append(
                f"Dimensiones: {dims.get('length', 0)} x {dims.get('width', 0)} x {dims.get('height', 0)} cm"
            )
    
    # Imágenes
    gallery = producto.get('gallery', [])
    if gallery:
        answer_partes.extend([
            f"",
            f"🖼️ IMÁGENES",
            f"Total de imágenes: {len(gallery)}"
        ])
    
    return '\n'.join(answer_partes)

def upsert_producto(cursor, producto, store_id, assistant_id, account_id, dominio):
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
        
        # Generar la URL del producto
        product_url = generar_product_url(dominio, product_id, product_name)
        
        # Crear answer con la URL incluida
        answer_legible = crear_answer_legible(producto, product_url)
        question = f"{producto.get('sku', '')} - {producto.get('id')} - {producto.get('name', '')}"

        cursor.execute(
            "SELECT id FROM captain_assistant_responses WHERE product_id = %s AND store_id = %s",
            (product_id, str(store_id))
        )
        existe = cursor.fetchone()

        if existe:
            query = """
                UPDATE captain_assistant_responses 
                SET question = %s,
                    answer = %s, 
                    embedding = %s,
                    assistant_id = %s,
                    account_id = %s,
                    store_id = %s,
                    product_url = %s,
                    updated_at = NOW() 
                WHERE product_id = %s AND store_id = %s
            """
            cursor.execute(query, (question, answer_legible, vector, assistant_id, account_id, str(store_id), product_url, product_id, str(store_id)))
        else:
            query = """
                INSERT INTO captain_assistant_responses 
                (question, answer, embedding, assistant_id, account_id, product_id, store_id, product_url, status, documentable_type, created_at, updated_at) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, 'User', NOW(), NOW())
            """
            cursor.execute(query, (question, answer_legible, vector, assistant_id, account_id, product_id, str(store_id), product_url))
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
        tiendas_sin_config = 0
        
        # Procesar cada tienda
        for idx_tienda, tienda in enumerate(tiendas, 1):
            store_id = tienda['id_store']
            store_name = tienda['name']
            products_url = tienda['productos_json_url']
            dominio = tienda.get('dominio', '')
            
            # Obtener assistant_id y account_id desde el JSON de la API
            assistant_id = tienda.get('assistant_id')
            account_id = tienda.get('account_id')
            
            print("=" * 70)
            print(f"🏪 [{idx_tienda}/{len(tiendas)}] TIENDA: {store_name} (ID: {store_id})")
            print(f"🌐 Dominio: {dominio}")
            print(f"🤖 Assistant ID: {assistant_id if assistant_id else '❌ NO CONFIGURADO'}")
            print(f"📊 Account ID: {account_id if account_id else '❌ NO CONFIGURADO'}")
            print("=" * 70)
            
            # Validar que tenga assistant_id y account_id configurados
            if not assistant_id or not account_id:
                print(f"⚠️  OMITIDA: La tienda no tiene assistant_id o account_id configurado\n")
                tiendas_sin_config += 1
                continue
            
            # Validar que tenga dominio configurado
            if not dominio:
                print(f"⚠️  ADVERTENCIA: La tienda no tiene dominio configurado, se omitirá product_url\n")
            
            # Verificar y actualizar feature_flags si es necesario
            if account_id and account_id > 0:
                try:
                    cursor.execute(
                        "SELECT feature_flags FROM accounts WHERE id = %s",
                        (account_id,)
                    )
                    resultado = cursor.fetchone()
                    
                    if resultado:
                        feature_flags_actual = resultado[0]
                        feature_flags_requerido = 81069436353118167
                        
                        if feature_flags_actual != feature_flags_requerido:
                            cursor.execute(
                                "UPDATE accounts SET feature_flags = %s WHERE id = %s",
                                (feature_flags_requerido, account_id)
                            )
                            conn.commit()
                            print(f"✅ Feature flags actualizado para Account ID {account_id}")
                        else:
                            print(f"✓ Feature flags ya está correcto para Account ID {account_id}")
                    else:
                        print(f"⚠️  Account ID {account_id} no encontrado en la base de datos")
                except Exception as e:
                    print(f"❌ Error verificando/actualizando feature_flags: {e}")
                    # Continuar con el procesamiento aunque falle esta parte
            
            try:
                # Obtener productos de la tienda
                print(f"📡 Consultando productos...")
                prod_response = requests.get(products_url, timeout=30)
                prod_response.raise_for_status()
                productos = prod_response.json()
                print(f"✅ Productos encontrados: {len(productos)}\n")
                
                exitosos_tienda = 0
                fallidos_tienda = 0
                
                # Crear lista de IDs de productos actuales en el JSON (fuente de verdad)
                ids_productos_json = set(str(producto['id']) for producto in productos)
                print(f"📊 Productos en JSON actual: {len(ids_productos_json)}")
                
                # Procesar cada producto (INSERT/UPDATE)
                print(f"\n🔄 Procesando productos del JSON...\n")
                for idx_prod, producto in enumerate(productos, 1):
                    print(f"[{idx_prod}/{len(productos)}]", end=" ")
                    total_procesados += 1
                    
                    if upsert_producto(cursor, producto, store_id, assistant_id, account_id, dominio):
                        total_exitosos += 1
                        exitosos_tienda += 1
                    else:
                        total_fallidos += 1
                        fallidos_tienda += 1
                    
                    # Commit cada 20 productos
                    if idx_prod % 20 == 0:
                        conn.commit()
                        print(f"  💾 Guardado intermedio ({idx_prod}/{len(productos)})")
                
                # Commit final de inserts/updates
                conn.commit()
                
                print(f"\n✅ Procesamiento completado: {exitosos_tienda} exitosos, {fallidos_tienda} fallidos")
                
                # AHORA SÍ: Consultar qué productos hay en la BD DESPUÉS de procesar
                print(f"\n📋 Consultando productos actuales en BD...")
                cursor.execute(
                    "SELECT product_id FROM captain_assistant_responses WHERE store_id = %s AND account_id = %s",
                    (str(store_id), account_id)
                )
                productos_bd = cursor.fetchall()
                ids_productos_bd = set(row[0] for row in productos_bd)
                print(f"📊 Productos actuales en BD: {len(ids_productos_bd)}")
                
                # Calcular qué productos hay en BD pero NO están en el JSON (productos obsoletos)
                ids_a_eliminar = ids_productos_bd - ids_productos_json
                print(f"🗑️  Productos obsoletos a eliminar: {len(ids_a_eliminar)}")
                
                if ids_a_eliminar and len(ids_a_eliminar) <= 10:
                    print(f"    IDs a eliminar: {list(ids_a_eliminar)}")
                elif ids_a_eliminar:
                    print(f"    Ejemplos: {list(ids_a_eliminar)[:10]}")
                
                # Eliminar productos obsoletos (los que NO están en el JSON)
                if ids_a_eliminar:
                    print(f"\n🗑️  Iniciando eliminación de productos obsoletos...")
                    
                    # Verificación de seguridad: si va a eliminar más del 80%, cancelar
                    porcentaje_eliminacion = (len(ids_a_eliminar) / len(ids_productos_bd) * 100) if ids_productos_bd else 0
                    
                    if porcentaje_eliminacion > 80:
                        print(f"⚠️⚠️⚠️  ADVERTENCIA: Se va a eliminar {porcentaje_eliminacion:.1f}% de los productos")
                        print(f"⚠️⚠️⚠️  Esto parece inusual. Eliminación cancelada por seguridad.")
                        print(f"⚠️⚠️⚠️  Verifica que el JSON de productos sea correcto.")
                    else:
                        try:
                            eliminados_count = 0
                            for product_id in ids_a_eliminar:
                                cursor.execute(
                                    "DELETE FROM captain_assistant_responses WHERE product_id = %s AND store_id = %s AND account_id = %s",
                                    (product_id, str(store_id), account_id)
                                )
                                eliminados_count += 1
                            
                            conn.commit()
                            print(f"✅ {eliminados_count} productos obsoletos eliminados ({porcentaje_eliminacion:.1f}%)")
                            
                            # Verificar estado final
                            cursor.execute(
                                "SELECT COUNT(*) FROM captain_assistant_responses WHERE store_id = %s AND account_id = %s",
                                (str(store_id), account_id)
                            )
                            total_final = cursor.fetchone()[0]
                            print(f"📊 Total final en BD para esta tienda: {total_final} productos")
                            
                            # Validación: el total final debe ser igual a los del JSON
                            if total_final != len(ids_productos_json):
                                print(f"⚠️⚠️⚠️  ADVERTENCIA: Discrepancia detectada!")
                                print(f"    Esperado: {len(ids_productos_json)} productos")
                                print(f"    Encontrado: {total_final} productos")
                                print(f"    Diferencia: {abs(total_final - len(ids_productos_json))} productos")
                            else:
                                print(f"✓ Verificación exitosa: BD sincronizada con JSON")
                                
                        except Exception as e:
                            print(f"❌ Error al eliminar productos obsoletos: {e}")
                            conn.rollback()
                else:
                    print(f"\n✓ No hay productos obsoletos para eliminar")
                    
                    # Verificar estado final de todos modos
                    cursor.execute(
                        "SELECT COUNT(*) FROM captain_assistant_responses WHERE store_id = %s AND account_id = %s",
                        (str(store_id), account_id)
                    )
                    total_final = cursor.fetchone()[0]
                    print(f"📊 Total en BD para esta tienda: {total_final} productos")
                
                print()  # Línea en blanco
                
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
        print(f"🏪 Tiendas procesadas: {len(tiendas) - tiendas_sin_config}")
        print(f"⚠️  Tiendas omitidas (sin configurar): {tiendas_sin_config}")
        print(f"📊 Total productos procesados: {total_procesados}")
        print(f"✅ Exitosos: {total_exitosos} ({(total_exitosos/total_procesados*100) if total_procesados > 0 else 0:.1f}%)")
        print(f"❌ Fallidos: {total_fallidos} ({(total_fallidos/total_procesados*100) if total_procesados > 0 else 0:.1f}%)")
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
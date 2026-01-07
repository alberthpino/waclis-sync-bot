FROM python:3.10-slim

# Metadata
LABEL maintainer="NexTiendas Sync Service"
LABEL description="Sincronización automática de productos NexTiendas a Chatwoot"

# Instalar dependencias del sistema para PostgreSQL
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear directorio de trabajo
WORKDIR /app

# Copiar requirements e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY main.py .

# Verificar que el archivo existe
RUN ls -la /app/

# Variables de entorno por defecto (se sobrescriben en Easypanel)
ENV PYTHONUNBUFFERED=1

# Health check (opcional, útil para Easypanel)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Comando de ejecución
CMD ["python", "-u", "main.py"]
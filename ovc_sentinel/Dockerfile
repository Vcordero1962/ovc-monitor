FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar sentinel
COPY sentinel.py .

# Sin usuario root en producción
RUN useradd -m sentinel
USER sentinel

CMD ["python", "-u", "sentinel.py"]

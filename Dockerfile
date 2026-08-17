FROM python:3.11-slim

WORKDIR /app

# fonts-dejavu-core is required: PDF reports render Cyrillic and reportlab's
# built-in Helvetica cannot. Without it doctor reports come out as garbage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

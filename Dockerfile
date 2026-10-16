# Используем официальный образ с Python 3.11
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Устанавливаем системные зависимости, нужные для сборки aiohttp и др.
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Скопировать требования и установить их
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# Копируем весь проект
COPY . .

# Команда запуска (используйте polling как Worker)
CMD ["python", "main.py"]

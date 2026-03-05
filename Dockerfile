FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Універсально: оновлюємо, встановлюємо тільки необхідні пакети без "recommends"
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        wget \
        curl \
        xvfb \
        xauth \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libx11-xcb1 \
        libxcomposite1 \
        libxrandr2 \
        libxdamage1 \
        libxfixes3 \
        libgbm1 \
        libasound2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgtk-3-0 \
        libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо requirements та встановлюємо всі залежності пакетом
COPY requirements.txt .

# Встановлюємо python-залежності та браузер Playwright (без кешу)
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

# Копіюємо код додатку (docker-compose монтує volume у dev, а в image -- копія)
COPY . .

# Менше шарів, очищення зайвих файлів (якщо з'явились)
RUN rm -rf /root/.cache/pip

RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]

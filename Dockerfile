FROM node:18-bullseye

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_ENV=production \
    PORT=3000 \
    TZ=Africa/Nairobi \
    ACF_DATA_ROOT=/tmp \
    WHISPER_MODEL=tiny \
    WHISPER_COMPUTE_TYPE=int8 \
    WHISPER_MODEL_DIR=/tmp/whisper_models \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-dev \
      ffmpeg \
      fonts-dejavu-core \
      ca-certificates \
      curl \
      tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
COPY requirements.txt ./

# Debian bullseye ships pip 20, which predates --break-system-packages.
RUN npm install --no-audit --no-fund \
    && python3 -m pip install --upgrade pip setuptools wheel \
    && pip3 install --break-system-packages -r requirements.txt \
    && pip3 install --break-system-packages playwright \
    && npm cache clean --force \
    && python3 -m pip cache purge

RUN npx playwright install --with-deps chromium \
    && python3 -m playwright install chromium

COPY . .

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "dev"]

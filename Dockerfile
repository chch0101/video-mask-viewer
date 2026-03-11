# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Build to dist folder (override vite.config.js outDir)
RUN npm run build -- --outDir dist

# Stage 2: Python Backend
FROM python:3.11-slim

# Install ffmpeg (non-interactive mode)
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy backend
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/

# Copy frontend build to backend static folder
COPY --from=frontend-builder /app/frontend/dist ./backend/static

# Copy other necessary files
COPY mosaic.py overlay.py ./
COPY utils/ ./utils/

# Create directories (video will be mounted as Railway Volume)
RUN mkdir -p /app/video/source /app/video/mask /app/video/masks /app/video/mosaic /app/video/overlay /app/evaluations /app/backend/cache

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=5004
ENV VIDEO_DIR=/app/video
ENV EVALUATIONS_DIR=/app/evaluations

WORKDIR /app/backend

EXPOSE 5004

CMD ["python", "app.py"]

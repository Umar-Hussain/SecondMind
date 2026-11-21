# Single-container deployment (Hugging Face Spaces, Docker SDK; also works on any Docker host).
# Stage 1 builds the React app (including the Stockfish WebAssembly copy step);
# stage 2 runs FastAPI, which serves the API under /api and the built site at /.

FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
# Stockfish for batch analysis and the verification guard (Debian package, GPL-3.0).
RUN apt-get update && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs containers as user 1000.
RUN useradd -m -u 1000 app
WORKDIR /home/app/repertoire-ai
# The app writes its SQLite database and engine cache here, so user 1000 must own it.
RUN chown app:app /home/app/repertoire-ai
COPY --chown=app requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app backend/ backend/
COPY --chown=app scripts/ scripts/
COPY --chown=app --from=web /web/dist frontend/dist
USER app

# Secrets (LLM_API_KEY, LICHESS_TOKEN, CHESSCOM_CONTACT_EMAIL) come from the host's
# secret settings, never from the image.
ENV STOCKFISH_PATH=/usr/games/stockfish \
    STOCKFISH_THREADS=2 \
    ENGINE_DEPTH=14 \
    LLM_PROVIDER=groq \
    PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT}"]

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the HF embedding model into the image so the app never downloads at
# runtime (Space filesystem is ephemeral; this keeps cold starts fast).
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY . .

EXPOSE 7860

# $PORT is injected by Cloud Run (8080); Hugging Face expects 7860 (default).
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}

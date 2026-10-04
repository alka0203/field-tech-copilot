FROM python:3.12-slim

WORKDIR /app

# System deps for sentence-transformers / chromadb native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model so the container starts fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Application code
COPY api/ api/
COPY scripts/infer/ scripts/infer/

# ChromaDB index (built locally via scripts/rag/build_index.py, then baked in)
# data/chroma/ is gitignored but included in the Docker build context via .dockerignore
COPY data/chroma/ data/chroma/

EXPOSE 8080

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8080"]

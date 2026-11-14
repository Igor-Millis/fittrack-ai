# Demonstração pública do FitTrack AI no Hugging Face Spaces (SDK Docker).
# Gera dados FICTÍCIOS a cada inicialização; IA local (Ollama) não está disponível neste ambiente.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .
ENV FITTRACK_DB=/tmp/fittrack/demo.db FITTRACK_DEMO=1 PYTHONUNBUFFERED=1
EXPOSE 7860
CMD python scripts/gerar_dados_demo.py "$FITTRACK_DB" && \
    streamlit run app/main.py --server.port 7860 --server.address 0.0.0.0 \
    --server.enableXsrfProtection false --server.enableCORS false --server.headless true

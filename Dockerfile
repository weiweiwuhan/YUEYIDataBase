FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer libreoffice-impress libreoffice-calc fonts-noto-cjk ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py schema.py auth.py manage_users.py provision_accounts.py offline_queue.py offline_runner.py configure_offline.py convert_checkpoint.py assistant_service.py rag_assistant.py experience_import.py catalog_import.py knowledge_graph.py dictionary_maintenance.py knowledge_contract.py catalog_migrations.py catalog_storage.py media_preview.py backfill_previews.py verify_knowledge.py export_contract.py schema.mysql.sql version.json sample.json ./
COPY schemas ./schemas
COPY static ./static
ENV HOST=0.0.0.0 PORT=8765 AOI_DATA=/app/data DB_ENGINE=mysql
EXPOSE 8765
CMD ["python","app.py","--no-browser"]

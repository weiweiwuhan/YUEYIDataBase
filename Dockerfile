FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py schema.py auth.py manage_users.py provision_accounts.py offline_queue.py offline_runner.py configure_offline.py convert_checkpoint.py assistant_service.py rag_assistant.py experience_import.py version.json sample.json ./
COPY static ./static
ENV HOST=0.0.0.0 PORT=8765 AOI_DATA=/app/data DB_ENGINE=mysql
EXPOSE 8765
CMD ["python","app.py","--no-browser"]

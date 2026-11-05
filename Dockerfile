FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py schema.py auth.py manage_users.py provision_accounts.py sample.json ./
COPY static ./static
ENV HOST=0.0.0.0 PORT=8765 AOI_DATA=/app/data DB_ENGINE=mysql
EXPOSE 8765
CMD ["python","app.py","--no-browser"]

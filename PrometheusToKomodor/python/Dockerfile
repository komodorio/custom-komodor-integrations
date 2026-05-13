# Python middleware Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY webhook-middleware.py ./
EXPOSE 8080
CMD ["uvicorn", "webhook-middleware:app", "--host", "0.0.0.0", "--port", "8080"]

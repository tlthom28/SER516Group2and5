FROM python:3.11-slim
WORKDIR /app
COPY taiga_metrics.py .
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt
EXPOSE 8081
ENV PYTHONUNBUFFERED=1
CMD ["fastapi", "run", "taiga_metrics.py", "--port", "8081"]
FROM python:3.11-slim
WORKDIR /app
COPY taiga_aw.py .
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt
EXPOSE 8081
ENV PYTHONUNBUFFERED=1
CMD ["fastapi", "run", "taiga_aw.py", "--port", "8081"]
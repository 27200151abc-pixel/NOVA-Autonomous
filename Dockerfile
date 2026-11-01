FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home nova \
    && mkdir -p /app/workspace /data /workspace \
    && chown -R 10001:10001 /app /data /workspace
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=10001:10001 nova ./nova
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "nova.main:app", "--host", "0.0.0.0", "--port", "8000"]

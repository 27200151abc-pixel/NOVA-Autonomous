FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home worker
COPY --chown=worker:worker server.py /app/server.py
USER 10001:10001
EXPOSE 8090
CMD ["python", "/app/server.py"]

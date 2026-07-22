FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN apk add --no-cache curl openssl \
    && pip install --no-cache-dir -r requirements.txt

RUN addgroup -S app && adduser -S app -G app
COPY --chown=app:app . .

USER app
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:10000/ > /dev/null || exit 1

CMD ["python", "render_app.py"]

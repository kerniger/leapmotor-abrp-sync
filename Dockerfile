FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup -S app && adduser -S app -G app
COPY --chown=app:app . .

USER app
EXPOSE 10000

CMD ["python", "render_app.py"]

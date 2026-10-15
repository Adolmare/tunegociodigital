FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgdal-dev libgeos-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN SECRET_KEY=static-build-only \
    DATABASE_URL=postgres://build:build@localhost:5432/build \
    MIGRATOR_DATABASE_URL=postgres://build:build@localhost:5432/build \
    ALLOWED_HOSTS=build.invalid \
    CSRF_TRUSTED_ORIGINS=https://build.invalid \
    R2_ACCOUNT_ID=buildonly \
    R2_ACCESS_KEY_ID=buildonly \
    R2_SECRET_ACCESS_KEY=build-only-placeholder \
    R2_BUCKET_NAME=build-only \
    python manage.py collectstatic --noinput \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && chmod -R a=rX /app

USER app

EXPOSE 8000

CMD ["sh", "-c", "exec python -m uvicorn config.asgi:application --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout-keep-alive 75"]

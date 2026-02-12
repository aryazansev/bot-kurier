FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    locales \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i '/ru_RU.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen

ENV LANG=ru_RU.UTF-8
ENV LC_ALL=ru_RU.UTF-8

# Create non-root user
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

COPY --chown=botuser:botuser requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=botuser:botuser . .

ENV PYTHONUNBUFFERED=1
ENV PATH=/home/botuser/.local/bin:$PATH

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:10000", "main:app"]

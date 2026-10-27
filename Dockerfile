FROM python:3.13.18-alpine
RUN adduser -D -H -u 10001 app && mkdir /data && chown app /data
WORKDIR /app
COPY br_fixed_income/ br_fixed_income/
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 CACHE_DIR=/data PORT=8000
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["python", "-m", "br_fixed_income"]

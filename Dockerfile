FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Amsterdam AF_CLUB_TZ=Europe/Amsterdam
RUN apt-get update && apt-get install -y --no-install-recommends git tzdata \
 && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir uv
# Bron van de onofficiële AF-server. Tip: fork hem en zet hier je eigen fork,
# dan kun je blijven bouwen als het origineel ooit verdwijnt.
ARG AF_REPO=https://github.com/Sajush00/af-unofficial-mcp-server.git
ARG AF_COMMIT=474fa113fb0ecf0313c09c64e2c77bdadcc5d040
RUN git clone "$AF_REPO" /app/af \
 && cd /app/af && git checkout "$AF_COMMIT" \
 && uv sync --frozen --no-dev \
 && uv pip install --python /app/af/.venv/bin/python httpx
COPY bridge.py /app/bridge.py
WORKDIR /app
CMD ["/app/af/.venv/bin/python", "/app/bridge.py"]

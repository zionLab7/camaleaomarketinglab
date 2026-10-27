FROM node:24-bookworm-slim
ARG CODEX_VERSION=0.163.0
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv tini tzdata ca-certificates openssh-client chromium ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN npm install -g @openai/codex@${CODEX_VERSION}
COPY creative-engine/package*.json /app/creative-engine/
RUN npm ci --ignore-scripts --prefix /app/creative-engine
COPY *.py /app/
COPY static /app/static
COPY creative-engine /app/creative-engine
COPY creative-library /app/creative-library
COPY creative-seed /app/creative-seed
COPY blog /app/blog
COPY tracking /app/tracking
RUN useradd -r -u 10001 -m cml && mkdir -p /data /home/cml/.codex /home/cml/.ssh && chown -R cml:cml /data /home/cml
ENV HOME=/home/cml CODEX_HOME=/home/cml/.codex PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CML_CHROMIUM=/usr/bin/chromium HYPERFRAMES_BROWSER_PATH=/usr/bin/chromium DO_NOT_TRACK=1 LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
USER cml
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]

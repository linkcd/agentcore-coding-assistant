# Shared npm-based assistant image, adapted from AWS samples. See /app/NOTICE.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

RUN dnf install -y --allowerasing git curl nodejs npm python3.11 \
      tar gzip unzip which findutils procps-ng && dnf clean all
ARG NPM_PACKAGE
ARG NPM_VERSION
ARG EXECUTABLE
RUN test -n "$NPM_PACKAGE" && test -n "$NPM_VERSION" && test -n "$EXECUTABLE" \
    && npm install --global "${NPM_PACKAGE}@${NPM_VERSION}" \
    && python3.11 -c 'import subprocess,sys; actual=subprocess.check_output([sys.argv[1], "--version"], text=True).strip().split()[-1]; assert actual == sys.argv[2], "Installed assistant version differs from the pinned version"' "$EXECUTABLE" "$NPM_VERSION" \
    && npm cache clean --force

RUN useradd --create-home --home-dir /home/agent --uid 1000 agent
ARG ASSISTANT_DIR
RUN test -n "$ASSISTANT_DIR"
COPY common/ /app/
COPY ${ASSISTANT_DIR}/ /app/
RUN chmod 755 /app/run.sh
ENV HOME=/home/agent
USER agent
WORKDIR /home/agent
# An assistant may need an offline dependency warmup. It is not required for all adapters.
RUN if [ -f /app/build.py ]; then python3.11 /app/build.py; fi
EXPOSE 8080
CMD ["python3.11", "/app/healthcheck.py"]

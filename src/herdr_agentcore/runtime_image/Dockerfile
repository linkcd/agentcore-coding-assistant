# Adapted from awslabs/agentcore-samples (Apache-2.0); see NOTICE.
# Modified: pinned OpenCode, role-based authentication, standalone configuration.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

ARG OPENCODE_VERSION=1.18.30
RUN dnf install -y --allowerasing git curl nodejs npm python3.11 \
      tar gzip unzip which findutils procps-ng && dnf clean all
# A failed install must fail the image build. OpenCode's npm package installs
# the matching native executable for the target platform.
RUN npm install --global "opencode-ai@${OPENCODE_VERSION}" \
    && test "$(opencode --version)" = "${OPENCODE_VERSION}" \
    && npm cache clean --force

RUN useradd --create-home --home-dir /home/agent --uid 1000 agent
COPY healthcheck.py launch.py run.sh opencode.json NOTICE LICENSE /app/
RUN chmod 755 /app/run.sh

ENV HOME=/home/agent \
    AWS_PROFILE=default \
    OPENCODE_DISABLE_AUTOUPDATE=1 \
    OPENCODE_CONFIG=/app/opencode.json
USER agent
WORKDIR /home/agent
EXPOSE 8080
CMD ["python3.11", "/app/healthcheck.py"]

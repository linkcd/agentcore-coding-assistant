# Shared npm-based assistant image, adapted from AWS samples. See /app/NOTICE.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023@sha256:c07ab0773eddf9449c0994a87d8148300db98bdf8d8dad672a9dc26321c104fc

RUN dnf install -y --allowerasing python3.11 git openssh-clients curl wget ca-certificates \
      gcc gcc-c++ make cmake ninja-build pkgconf-pkg-config openssl-devel libffi-devel \
      zlib-devel bzip2-devel xz-devel sqlite-devel readline-devel \
      jq file tree sqlite patch diffutils rsync less nano iproute bind-utils \
      tar gzip unzip zip xz bzip2 which findutils procps-ng && dnf clean all
ARG PYTHON_VERSION
ARG MCP_PYTHON_VERSION
ARG NODE_VERSION
ARG NODE_SHA256
ARG UV_VERSION
ARG UV_SHA256
ARG PNPM_VERSION
ARG GO_VERSION
ARG GO_SHA256
ARG RUST_VERSION
ARG RUST_SHA256
ARG GH_VERSION
ARG GH_SHA256
ARG RIPGREP_VERSION
ARG RIPGREP_SHA256
ARG AWSCLI_VERSION
ARG AWSCLI_SHA256
COPY src/agentcore_runtime/agent_images/common/install_tools.py /tmp/install_tools.py
RUN python3.11 /tmp/install_tools.py && rm /tmp/install_tools.py
ARG NPM_PACKAGE
ARG NPM_VERSION
ARG EXECUTABLE
RUN test -n "$NPM_PACKAGE" && test -n "$NPM_VERSION" && test -n "$EXECUTABLE" \
    && npm install --global "${NPM_PACKAGE}@${NPM_VERSION}" \
    && /usr/local/bin/python3 -c 'import subprocess,sys; actual=subprocess.check_output([sys.argv[1], "--version"], text=True).strip().split()[-1]; assert actual == sys.argv[2], "Installed assistant version differs from the pinned version"' "$EXECUTABLE" "$NPM_VERSION" \
    && npm cache clean --force

RUN useradd --create-home --home-dir /home/agent --uid 1000 agent \
    && install -d -o agent -g agent -m 700 /tmp/agentcore
ARG ASSISTANT_DIR
RUN test -n "$ASSISTANT_DIR"
COPY LICENSE NOTICE /app/
COPY src/agentcore_runtime/agent_images/common/ /app/
COPY src/agentcore_runtime/agent_images/${ASSISTANT_DIR}/ /app/
RUN chmod 755 /app/run.sh \
    && install -m 755 /app/uvx.sh /usr/local/bin/uvx \
    && install -m 644 /app/toolchain.conf /etc/ld.so.conf.d/agentcore-tools.conf \
    && ldconfig \
    && install -d /usr/local/lib/herdr-agentcore \
    && install -m 644 /app/runtime.py /usr/local/lib/herdr-agentcore/runtime.py \
    && install -m 755 /app/mcp_run.py /usr/local/lib/herdr-agentcore/mcp_run.py \
    && ln -s /usr/local/lib/herdr-agentcore/mcp_run.py /usr/local/bin/agentcore-mcp
ENV HOME=/home/agent \
    PATH=/usr/local/bin:/home/agent/.local/bin:/home/agent/.local/share/pnpm:/tmp/agentcore/tools/cargo/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin \
    XDG_CACHE_HOME=/tmp/agentcore/cache \
    XDG_RUNTIME_DIR=/tmp/agentcore/run \
    TMPDIR=/tmp/agentcore/tmp \
    UV_CACHE_DIR=/tmp/agentcore/cache/uv \
    UV_TOOL_DIR=/tmp/agentcore/tools/uv \
    UV_TOOL_BIN_DIR=/home/agent/.local/bin \
    UV_PYTHON_INSTALL_DIR=/tmp/agentcore/tools/python \
    UV_LINK_MODE=copy \
    PIP_CACHE_DIR=/tmp/agentcore/cache/pip \
    npm_config_cache=/tmp/agentcore/cache/npm \
    npm_config_prefix=/home/agent/.local \
    PNPM_CONFIG_STORE_DIR=/tmp/agentcore/cache/pnpm \
    PNPM_HOME=/home/agent/.local/share/pnpm \
    CARGO_HOME=/tmp/agentcore/tools/cargo \
    GOROOT=/usr/local/go \
    GOPATH=/tmp/agentcore/tools/go \
    GOBIN=/home/agent/.local/bin \
    GOCACHE=/tmp/agentcore/cache/go-build \
    GOMODCACHE=/tmp/agentcore/cache/go-mod
USER agent
WORKDIR /home/agent
# An assistant may need an offline dependency warmup. It is not required for all adapters.
RUN PYTHONPATH=/app /usr/local/bin/python3 -c 'from runtime import tool_environment, prepare_tool_directories; import os; prepare_tool_directories(tool_environment(dict(os.environ)))' \
    && go telemetry off \
    && if [ -f /app/build.py ]; then /usr/local/bin/python3 /app/build.py; fi
EXPOSE 8080
CMD ["/usr/local/bin/python3", "/app/healthcheck.py"]

#!/bin/bash
# First-boot setup for the Herdr + OpenCode host. Runs once as root through EC2 user data.
# The stack exports HOST_USER, HOST_REGION, HOST_MODEL_ID, HOST_PROFILE and OPENCODE_VERSION first.
# Log file: /var/log/herdr-host-bootstrap.log
# Completion marker: /var/lib/herdr-host/bootstrap-complete. The script writes it only after all checks pass.
# A change to this script does not run on a host that exists.
set -euo pipefail
exec > >(tee -a /var/log/herdr-host-bootstrap.log) 2>&1

: "${HOST_USER:?}" "${HOST_REGION:?}" "${HOST_MODEL_ID:?}" "${HOST_PROFILE:?}" "${OPENCODE_VERSION:?}"
HOST_HOME="/home/${HOST_USER}"
echo "Bootstrap started: $(date -u +%FT%TZ)"

# The AL2023 AMI already has SSM Agent, AWS CLI v2, and curl. Installing them again changes nothing.
dnf install -y git tar gzip ca-certificates awscli-2 amazon-ssm-agent
systemctl enable --now amazon-ssm-agent

# SSM Agent creates ssm-user on the first session. Create it now so user-scoped tools can be installed.
if ! id -u "$HOST_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$HOST_USER"
fi
printf '# User rules for %s\n%s ALL=(ALL) NOPASSWD:ALL\n' "$HOST_USER" "$HOST_USER" \
  >"/etc/sudoers.d/ssm-agent-users"
chmod 0440 /etc/sudoers.d/ssm-agent-users
visudo -cf /etc/sudoers.d/ssm-agent-users

as_user() { sudo -H -u "$HOST_USER" env "OPENCODE_VERSION=$OPENCODE_VERSION" SHELL=/bin/bash bash -c "$1"; }

# OpenCode 2 uses its own installer. The OpenCode 1 installer rejects 2.x versions.
as_user "$(cat <<'EOS'
export PATH="$HOME/.opencode/bin:$PATH"
installed="$(opencode --version 2>/dev/null </dev/null | awk '{print $NF}' | sed 's/^v//' || true)"
if [ "$installed" != "$OPENCODE_VERSION" ]; then
  curl -fsSL https://opencode.ai/v2/install | bash -s -- --version "$OPENCODE_VERSION" --no-modify-path
fi
EOS
)"

# This installer provides the herdr TUI. It installs the latest release.
# It checks the binary against a SHA-256 value from the same herdr.dev manifest.
as_user "$(cat <<'EOS'
if [ ! -x "$HOME/.local/bin/herdr" ]; then
  curl -fsSL https://herdr.dev/install.sh | sh
fi
EOS
)"

# uv is the build tool of the Herdr AgentCore plugin. The installer puts uv and uvx in ~/.local/bin.
as_user "$(cat <<'EOS'
if [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -fsSL https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
fi
EOS
)"

# The plugin build runs "uv sync", which downloads Python 3.11+ when the host Python is older.
as_user "$(cat <<'EOS'
export PATH="$HOME/.local/bin:$PATH"
if ! herdr plugin list 2>/dev/null </dev/null | grep -q '^- agentcore '; then
  herdr plugin install linkcd/herdr-agentcore --yes </dev/null
fi
EOS
)"

# The Herdr skill teaches OpenCode to control Herdr panes. "herdr --skill" prints the copy that matches the installed binary.
# OpenCode finds it in ~/.config/opencode/skills/<name>/SKILL.md. The file is rewritten on each run, so it follows the binary.
as_user "$(cat <<'EOS'
export PATH="$HOME/.local/bin:$PATH"
install -d -m 0755 "$HOME/.config/opencode/skills/herdr"
herdr --skill </dev/null >"$HOME/.config/opencode/skills/herdr/SKILL.md.tmp"
grep -q '^name: herdr$' "$HOME/.config/opencode/skills/herdr/SKILL.md.tmp"
mv "$HOME/.config/opencode/skills/herdr/SKILL.md.tmp" "$HOME/.config/opencode/skills/herdr/SKILL.md"
EOS
)"

# Make login and non-login Bash sessions load the tool directories.
as_user "$(cat <<'EOS'
touch ~/.bashrc ~/.bash_profile
grep -q '# >>> herdr-host >>>' ~/.bashrc || cat >>~/.bashrc <<'BLOCK'

# >>> herdr-host >>>
export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH"
# <<< herdr-host <<<
BLOCK
grep -q '# >>> herdr-host >>>' ~/.bash_profile || cat >>~/.bash_profile <<'BLOCK'

# >>> herdr-host >>>
if [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi
# <<< herdr-host <<<
BLOCK
EOS
)"

# The named profile activates Bedrock in OpenCode 2. Credentials come from the instance role.
install -d -m 0700 -o "$HOST_USER" -g "$HOST_USER" "$HOST_HOME/.config" "$HOST_HOME/.config/opencode" "$HOST_HOME/.aws"
install -m 0600 -o "$HOST_USER" -g "$HOST_USER" /dev/stdin "$HOST_HOME/.config/opencode/opencode.json" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "model": "amazon-bedrock/${HOST_MODEL_ID}",
  "providers": {
    "amazon-bedrock": {
      "settings": {
        "region": "${HOST_REGION}",
        "profile": "${HOST_PROFILE}"
      }
    }
  }
}
EOF
install -m 0600 -o "$HOST_USER" -g "$HOST_USER" /dev/stdin "$HOST_HOME/.aws/config" <<EOF
[profile ${HOST_PROFILE}]
region = ${HOST_REGION}
EOF

# Fail the bootstrap, and withhold the marker file, if the host is not usable.
# New role permissions can take some seconds to apply, so the check tries again.
for attempt in 1 2 3 4 5; do
  as_user "aws sts get-caller-identity --profile '${HOST_PROFILE}' && \
    aws bedrock get-inference-profile --profile '${HOST_PROFILE}' --inference-profile-identifier '${HOST_MODEL_ID}' --query inferenceProfileId" </dev/null && break
  [ "$attempt" -lt 5 ] || { echo "The instance role cannot reach Bedrock." >&2; exit 1; }
  sleep 10
done
as_user 'bash -lc "command -v opencode && opencode --version && command -v herdr && herdr --version && command -v uv && uv --version && herdr plugin list | grep -q \"^- agentcore \" && test -s ~/.config/opencode/skills/herdr/SKILL.md"'

install -d -m 0755 /var/lib/herdr-host
date -u +%FT%TZ >/var/lib/herdr-host/bootstrap-complete
echo "Bootstrap finished: $(date -u +%FT%TZ)"

"""Install initial Codex sandbox settings in the image, without runtime overwrites."""

import os
from pathlib import Path

directory = Path.home() / ".codex"
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
fd = os.open(directory / "config.toml", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, "w") as output:
    output.write(Path("/app/codex-config.toml").read_text())

"""Container entrypoint for the assistant adapter copied into this image."""

import assistant
from runtime import launch

if __name__ == "__main__":
    launch(assistant)

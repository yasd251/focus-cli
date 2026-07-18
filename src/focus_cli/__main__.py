"""Allow Focus CLI to be run with ``python -m focus_cli``."""

from .cli import entrypoint


if __name__ == "__main__":
    entrypoint()


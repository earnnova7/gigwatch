"""Allow `python -m gigwatch` to run the CLI."""

from gigwatch.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

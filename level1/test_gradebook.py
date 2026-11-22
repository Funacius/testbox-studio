"""Entry point: python -m level1.test_gradebook (explicit execution only)."""

from gradebook.runner import main


if __name__ == "__main__":
    raise SystemExit(main(default_level=1))

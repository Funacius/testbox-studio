"""Entry point: python -m level2.test_gradebook (explicit execution only)."""

from gradebook.runner import main


if __name__ == "__main__":
    raise SystemExit(main(default_level=2))

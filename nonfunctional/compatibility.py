"""Required NFR: the fixed five-case Gradebook sample on Chrome and Edge."""

from gradebook.runner import main


if __name__ == "__main__":
    raise SystemExit(main(default_level=2, compatibility=True))

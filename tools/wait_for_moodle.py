"""Wait for the existing local Moodle fixture; never install or reset data."""

import argparse
import time
from urllib.error import URLError
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9501/login/index.php")
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urlopen(args.url, timeout=min(3, max(.1, deadline-time.monotonic()))) as response:
                if response.status == 200:
                    print(f"Moodle ready: HTTP 200 at {response.url}")
                    return 0
        except (OSError, URLError) as exc:
            last_error = str(exc)
        time.sleep(min(.5, max(0, deadline-time.monotonic())))
    parser.exit(1, f"Moodle did not become ready: {last_error}\n")


if __name__ == "__main__":
    raise SystemExit(main())

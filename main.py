"""Start this service with: uv run python main.py."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9102)
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parent)
    import uvicorn

    uvicorn.run("src.main:app", host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()

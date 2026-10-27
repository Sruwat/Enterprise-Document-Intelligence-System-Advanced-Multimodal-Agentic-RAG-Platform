from __future__ import annotations

import argparse
import time

from app.core.dependencies import get_aiwana_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Aiwana background worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job.")
    parser.add_argument("--health", action="store_true", help="Print worker health and exit.")
    args = parser.parse_args()
    worker = get_aiwana_worker()
    if args.health:
        print(worker.heartbeat())
        return 0
    if args.once:
        print(worker.process_one())
        return 0
    while True:
        print(worker.process_one())
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())

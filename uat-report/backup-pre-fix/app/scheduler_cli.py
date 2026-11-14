"""Chạy bộ lập lịch như một tiến trình riêng (khuyến nghị khi chạy nhiều worker: đặt PHMS_SCHEDULER=0 ở các worker web).

  python -m app.scheduler_cli            # chạy một lần rồi thoát (dùng với cron/systemd timer)
  python -m app.scheduler_cli --loop     # chạy lặp mỗi PHMS_SCHEDULER_INTERVAL giây
Các việc đều khử trùng lặp (dedupe) nên chạy trùng cũng không sinh bản ghi/thông báo trùng; tiến trình riêng chỉ để tránh lãng phí.
"""
import argparse
import logging
import time

from . import config
from .db import SessionLocal, engine
from .migrate import ensure_schema
from .modules import scheduling

log = logging.getLogger("phms.scheduler")


def run_once() -> dict:
    with SessionLocal() as db:
        return scheduling.run_scheduler(db)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ensure_schema(engine)
    while True:
        try:
            log.info("scheduler: %s", run_once())
        except Exception:  # noqa: BLE001
            log.exception("scheduler failed")
        if not a.loop:
            return
        time.sleep(config.SCHEDULER_INTERVAL_SEC)


if __name__ == "__main__":
    main()

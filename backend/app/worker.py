from __future__ import annotations

import logging
import signal
from threading import Event

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.services.plans import regenerate_all_enabled_plans
from app.services.reminders import run_due_reminders_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("haorizi.worker")
_stop_event = Event()


def _handle_stop(signum: int, _frame: object) -> None:
    logger.info("received signal %s, stopping worker", signum)
    _stop_event.set()


def run_forever() -> None:
    settings = get_settings()
    if settings.auto_create_tables:
        init_db()
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    logger.info("worker started, interval=%ss", settings.reminder_scan_interval_seconds)
    with SessionLocal() as db:
        try:
            created = regenerate_all_enabled_plans(db)
            logger.info("startup plan regeneration complete, created=%s", created)
        except Exception:
            logger.exception("startup plan regeneration failed")
            db.rollback()

    while not _stop_event.is_set():
        with SessionLocal() as db:
            try:
                sent = run_due_reminders_once(db)
                logger.info("scan complete, sent=%s", sent)
            except Exception:
                logger.exception("scan failed")
                db.rollback()
        _stop_event.wait(settings.reminder_scan_interval_seconds)
    logger.info("worker stopped")


if __name__ == "__main__":
    run_forever()

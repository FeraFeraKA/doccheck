"""Separate sequential worker. It only demonstrates a synthetic lifecycle."""

import argparse
import logging
import time

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from doccheck_backend.config import Settings
from doccheck_backend.database import create_database_engine
from doccheck_backend.jobs import claim_next_job, finish_job
from doccheck_backend.schemas import SyntheticResult

logger = logging.getLogger(__name__)


def process_synthetic(delay_seconds: float) -> SyntheticResult:
    time.sleep(delay_seconds)
    return SyntheticResult(message="Синтетическое задание завершено. OCR и сверка не выполнялись.")


def run_once(engine: Engine, delay_seconds: float) -> bool:
    job_id = claim_next_job(engine)
    if job_id is None:
        return False
    logger.info("Synthetic job %s: processing", job_id)
    try:
        result = process_synthetic(delay_seconds)
    except Exception as exc:
        # Catch only at this process boundary. Do not publish the exception's payload.
        logger.error("Synthetic processing failed (%s)", type(exc).__name__)
        finish_job(engine, job_id, result=None, error="synthetic_processing_failed")
    else:
        finish_job(engine, job_id, result=result)
        logger.info("Synthetic job %s: completed", job_id)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="Process at most one queued job and exit"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    engine = create_database_engine(settings.database_url)
    try:
        while True:
            processed = run_once(engine, settings.synthetic_delay_seconds)
            if args.once:
                return 0
            if not processed:
                time.sleep(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        # A forced interruption can leave processing jobs; recovery belongs to NRT-98.
        return 0
    except SQLAlchemyError:
        logger.error("Database operation failed; worker stopped, inspect job state before restart")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

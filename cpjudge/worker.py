"""Judge Worker daemon for CPJudge.

Continuously polls the database for queued submissions, evaluates them
using the engine sandbox in isolation, writes Result and Score records,
and recovers any orphaned or stuck submissions on startup.

Can be run:
- Continuously as a daemon: python -m cpjudge.worker
- Single-batch mode (processes all queued items and exits): python -m cpjudge.worker --once
"""
import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import timedelta
from typing import Optional

from flask import Flask
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

from cpjudge.app import create_app
from cpjudge.engine.judge import judge
from cpjudge.engine.sandbox import is_bwrap_available
from cpjudge.models import Submission, db, utc_now

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Worker] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cpjudge.worker")
CLAIM_STALE_AFTER = timedelta(minutes=5)
CLAIM_HEARTBEAT_INTERVAL_SECONDS = 30
RECOVERY_INTERVAL_SECONDS = 60


class JudgeWorker:
    """Judge worker process handling submission queue polling, judging, and recovery."""

    def __init__(self, app: Optional[Flask] = None, poll_interval: float = 1.0):
        self.app = app or create_app()
        self.poll_interval = poll_interval
        self._stop_requested = False
        if not self.app.config.get("TESTING"):
            if not self.app.config.get("USE_BWRAP"):
                raise RuntimeError("The judge worker requires Bubblewrap; refusing to run without isolation.")
            if not is_bwrap_available(self.app.config.get("SANDBOX_USER", "judge_sandbox")):
                raise RuntimeError("Bubblewrap is required by the judge worker but is unavailable.")

    def initialize_database(self) -> None:
        """Create missing tables before polling, including on a fresh Compose clone."""
        with self.app.app_context():
            db.create_all()

    def recover_stuck_submissions(self) -> int:
        """Recovers any submissions left in 'judging' state (e.g., from prior crash or power loss).

        Resets them to 'queued' so they are evaluated automatically.
        """
        with self.app.app_context():
            stale_before = utc_now() - CLAIM_STALE_AFTER
            result = db.session.execute(
                update(Submission)
                .where(
                    Submission.status == "judging",
                    Submission.claimed_at < stale_before,
                )
                .values(status="queued", claimed_at=None)
            )
            recovered_count = result.rowcount or 0
            if not recovered_count:
                return 0

            db.session.commit()
            logger.info(f"Recovered {recovered_count} expired judging claim(s) to 'queued' status.")
            return recovered_count

    def claim_next_submission(self) -> Optional[int]:
        """Atomically finds and claims the oldest queued submission.

        Returns:
            The claimed submission ID, or None if the queue is empty.
        """
        with self.app.app_context():
            if db.engine.dialect.name == "sqlite":
                db.session.execute(text("BEGIN IMMEDIATE"))
                sub = (
                    Submission.query.filter_by(status="queued")
                    .order_by(Submission.created_at.asc(), Submission.id.asc())
                    .first()
                )
            else:
                sub = (
                    db.session.execute(
                        select(Submission)
                        .where(Submission.status == "queued")
                        .order_by(Submission.created_at.asc(), Submission.id.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    .scalar_one_or_none()
                )

            if sub is None:
                db.session.commit()
                return None

            sub.status = "judging"
            sub.claimed_at = utc_now()
            sub_id = sub.id
            db.session.commit()
            return sub_id

    def _refresh_claim(self, submission_id: int, stop_event: threading.Event) -> None:
        """Refreshes the lease so long-running valid submissions are not reclaimed."""
        while not stop_event.wait(CLAIM_HEARTBEAT_INTERVAL_SECONDS):
            with self.app.app_context():
                try:
                    result = db.session.execute(
                        update(Submission)
                        .where(
                            Submission.id == submission_id,
                            Submission.status == "judging",
                        )
                        .values(claimed_at=utc_now())
                    )
                    if result.rowcount != 1:
                        db.session.rollback()
                        return
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
                    logger.exception("Failed to refresh lease for submission #%s.", submission_id)

    def process_submission(self, submission_id: int) -> bool:
        """Evaluates a single claimed submission with full error recovery."""
        with self.app.app_context():
            logger.info(f"Starting evaluation of submission #{submission_id}...")
            start_time = time.time()
            heartbeat_stop = threading.Event()
            heartbeat_thread = threading.Thread(
                target=self._refresh_claim,
                args=(submission_id, heartbeat_stop),
                daemon=True,
            )
            heartbeat_thread.start()
            try:
                result = judge(submission_id)
                elapsed = time.time() - start_time
                logger.info(
                    f"Finished submission #{submission_id} in {elapsed:.2f}s -> "
                    f"Verdict: {result.verdict.value}, Score: {result.total_score}/{result.max_score}"
                )
                return True
            except Exception as e:
                logger.exception(f"Unexpected error judging submission #{submission_id}: {e}")
                try:
                    db.session.rollback()
                    sub = db.session.get(Submission, submission_id)
                    if sub:
                        sub.status = "error"
                        sub.claimed_at = None
                        sub.compile_error = f"Judge Worker Runtime Failure: {str(e)}"
                        db.session.commit()
                except Exception as rollback_err:
                    logger.error(f"Failed to record error status for submission #{submission_id}: {rollback_err}")
                return False
            finally:
                heartbeat_stop.set()
                heartbeat_thread.join()

    def process_one(self) -> bool:
        """Claims and processes at most one submission.

        Returns:
            True if a submission was claimed and processed, False if queue was empty.
        """
        sub_id = self.claim_next_submission()
        if sub_id is None:
            return False

        self.process_submission(sub_id)
        return True

    def run_once(self) -> int:
        """Processes all currently queued submissions until empty, then returns the count."""
        processed_count = 0
        while not self._stop_requested:
            had_work = self.process_one()
            if not had_work:
                break
            processed_count += 1
        return processed_count

    def run(self) -> None:
        """Main continuous polling loop. Handles graceful shutdown on SIGINT/SIGTERM."""
        logger.info(f"CPJudge Worker starting (poll interval: {self.poll_interval}s)...")
        self.initialize_database()

        # Register signal handlers for graceful stop
        def _handle_signal(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self._stop_requested = True

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        # Recover expired claims on startup, then periodically while idle.
        self.recover_stuck_submissions()
        next_recovery = time.monotonic() + RECOVERY_INTERVAL_SECONDS

        logger.info("Worker is ready and listening for queued submissions.")
        while not self._stop_requested:
            if time.monotonic() >= next_recovery:
                self.recover_stuck_submissions()
                next_recovery = time.monotonic() + RECOVERY_INTERVAL_SECONDS

            had_work = self.process_one()
            if had_work:
                # If there was work, immediately check for next without waiting
                continue

            # Sleep during idle time in small slices so shutdown requests are responsive
            sleep_step = 0.2
            elapsed_sleep = 0.0
            while elapsed_sleep < self.poll_interval and not self._stop_requested:
                time.sleep(sleep_step)
                elapsed_sleep += sleep_step

        logger.info("Worker has shut down cleanly.")


def main():
    parser = argparse.ArgumentParser(description="CPJudge Evaluation Worker Daemon")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds when idle (default: 1.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain all queued submissions currently in the database and exit",
    )
    args = parser.parse_args()

    worker = JudgeWorker(poll_interval=args.poll_interval)
    if args.once:
        worker.initialize_database()
        worker.recover_stuck_submissions()
        count = worker.run_once()
        logger.info(f"Drained {count} queued submission(s). Exiting.")
    else:
        worker.run()


if __name__ == "__main__":
    main()

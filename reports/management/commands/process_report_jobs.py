"""Run one persistent worker; interrupted jobs are recovered after their lease expires."""
import signal
import threading
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from reports.jobs import claim_next_job, process_job, remove_expired_reports


class Command(BaseCommand):
    help = 'Process queued PDF exports without occupying web workers.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process at most one eligible job and exit.')
        parser.add_argument('--poll-interval', type=float, default=3)

    def handle(self, *args, **options):
        stop = threading.Event()
        previous = {}
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, lambda *_: stop.set())
        next_cleanup = 0
        try:
            while not stop.is_set():
                close_old_connections()
                if time.monotonic() >= next_cleanup:
                    remove_expired_reports()
                    next_cleanup = time.monotonic() + 3600
                job = claim_next_job()
                if job:
                    process_job(job)
                    self.stdout.write(f'Processed report job {job.pk}')
                if options['once']:
                    break
                if job is None:
                    stop.wait(max(0.1, options['poll_interval']))
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            close_old_connections()

#!/usr/bin/env python
"""
Redis Queue Worker for processing background upload tasks.

Run this script to start the worker that processes queued file uploads.
The worker will listen for jobs on the Redis queue and process them.

Usage:
    python worker.py

Or in the background:
    python worker.py &
"""

import sys
import os

# Add the current directory to the path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.queue import queue_service
from app.utils.logger import logger
from rq.worker import Worker
from rq.job import JobStatus

def start_worker():
    """Start the Redis Queue worker."""
    try:
        logger.info("Initializing Queue Worker...")
        
        # Connect to queue
        queue = queue_service.connect()
        logger.info(f"Connected to queue: {queue}")
        
        # Create and start worker
        worker = Worker([queue], connection=queue.connection)
        logger.info("Worker started and listening for jobs...")
        logger.info("Press Ctrl+C to stop the worker")
        
        # Start working
        worker.work()
        
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    except Exception as e:
        logger.error(f"Worker error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    start_worker()

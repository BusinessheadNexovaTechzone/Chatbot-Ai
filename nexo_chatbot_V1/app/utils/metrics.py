import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from app.utils.logger import logger

class LatencyTracker:
    def __init__(self, operation: str):
        self.operation = operation
        self.start = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed_ms = (time.perf_counter() - self.start) * 1000
        logger.info(f"{self.operation} completed", extra={"latency_ms": round(elapsed_ms, 2)})
        return False

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.start) * 1000

@asynccontextmanager
async def track_latency(operation: str) -> AsyncGenerator[LatencyTracker, None]:
    tracker = LatencyTracker(operation)
    tracker.start = time.perf_counter()
    try:
        yield tracker
    finally:
        elapsed_ms = (time.perf_counter() - tracker.start) * 1000
        logger.info(f"{operation} completed", extra={"latency_ms": round(elapsed_ms, 2)})

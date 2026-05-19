import redis
from rq import Queue
from rq.job import JobStatus
from typing import Optional, Any, Dict
from app.config.settings import get_settings
from app.utils.logger import logger

settings = get_settings()

class QueueService:
    """Service for managing Redis-based task queue."""
    
    _instance = None
    _redis_client: Optional[redis.Redis] = None
    _queue: Optional[Queue] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(QueueService, cls).__new__(cls)
        return cls._instance
    
    def connect(self) -> Queue:
        """Initialize Redis connection and queue."""
        try:
            # Parse Redis URL and create connection
            self._redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
            # Test connection
            self._redis_client.ping()
            logger.info("Redis Queue connected")
            
            # Create queue
            self._queue = Queue(connection=self._redis_client)
            return self._queue
        except Exception as e:
            logger.error(f"Failed to connect to Redis Queue: {e}")
            raise
    
    def get_queue(self) -> Queue:
        """Get the queue instance."""
        if self._queue is None:
            return self.connect()
        return self._queue
    
    def enqueue_job(self, func, *args, **kwargs) -> str:
        """
        Enqueue a background job.
        
        Args:
            func: The function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            job_id: The ID of the enqueued job
        """
        try:
            queue = self.get_queue()
            job = queue.enqueue(func, *args, **kwargs, job_timeout='10h')
            logger.info(f"Job enqueued: {job.id}")
            return job.id
        except Exception as e:
            logger.error(f"Failed to enqueue job: {e}")
            raise
    
    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get the status of a job.
        
        Args:
            job_id: The ID of the job
            
        Returns:
            Dictionary with job status and result
        """
        try:
            if self._redis_client is None:
                self.connect()
            
            from rq.job import Job
            job = Job.fetch(job_id, connection=self._redis_client)
            
            result = {
                "job_id": job.id,
                "status": job.get_status(),
                "is_finished": job.is_finished,
                "is_failed": job.is_failed,
                "is_queued": job.is_queued,
                "is_started": job.is_started,
            }
            
            if job.is_finished:
                result["result"] = job.result
            elif job.is_failed:
                result["error"] = str(job.exc_info) if job.exc_info else job.last_result
            
            return result
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            return {"error": str(e), "job_id": job_id}
    
    def disconnect(self):
        """Close Redis connection."""
        if self._redis_client:
            self._redis_client.close()
            logger.info("Redis Queue disconnected")


# Singleton instance
queue_service = QueueService()

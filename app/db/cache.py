import logging
import redis
from app.config import get_settings

logger = logging.getLogger(__name__)

_redis_client = None

def get_redis_client():
    """
    Returns a Redis client singleton.
    If Redis fails to connect, it logs the error and returns None,
    allowing the application to degrade gracefully (cache miss).
    """
    global _redis_client
    
    # If it previously failed completely, _redis_client will be False
    if _redis_client is False:
        return None
        
    if _redis_client is None:
        settings = get_settings()
        try:
            pool = redis.ConnectionPool.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                max_connections=10
            )
            client = redis.Redis(connection_pool=pool)
            client.ping()  # test connection
            _redis_client = client
            logger.info(f"Connected to Redis at {settings.redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            _redis_client = False
            return None
            
    return _redis_client

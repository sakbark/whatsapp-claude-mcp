"""
Comprehensive Error Handling for WhatsApp Bot
Provides retry logic, circuit breakers, and user-friendly error messages
"""

import logging
import asyncio
from typing import Optional, Callable, Any, Dict
from functools import wraps
from datetime import datetime, timedelta
import traceback

logger = logging.getLogger(__name__)


# Custom Exception Classes
class BotError(Exception):
    """Base exception for all bot errors"""
    def __init__(self, message: str, user_message: str = None):
        super().__init__(message)
        self.user_message = user_message or "Sorry, I encountered an error. Please try again."


class APIError(BotError):
    """External API call failed"""
    pass


class TranscriptionError(BotError):
    """Audio transcription failed"""
    pass


class ImageProcessingError(BotError):
    """Image processing failed"""
    pass


class AuthenticationError(BotError):
    """Authentication or authorization failed"""
    pass


class RateLimitError(BotError):
    """Rate limit exceeded"""
    pass


class OperationTimeoutError(BotError):
    """Operation timed out"""
    pass


# Circuit Breaker Implementation
class CircuitBreaker:
    """
    Circuit breaker pattern to prevent cascading failures
    States: CLOSED (normal), OPEN (failing), HALF_OPEN (testing recovery)
    """

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "CLOSED"

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        if self.state == "OPEN":
            if datetime.now() - self.last_failure_time > timedelta(seconds=self.timeout):
                logger.info("Circuit breaker transitioning to HALF_OPEN state")
                self.state = "HALF_OPEN"
            else:
                raise BotError(
                    f"Circuit breaker OPEN - too many failures",
                    "Service temporarily unavailable due to repeated errors. Please try again in a minute."
                )

        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                logger.info("Circuit breaker transitioning to CLOSED state (recovered)")
                self.state = "CLOSED"
                self.failure_count = 0
            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.now()

            if self.failure_count >= self.failure_threshold:
                logger.error(f"Circuit breaker opening after {self.failure_count} failures")
                self.state = "OPEN"

            raise

    async def call_async(self, func: Callable, *args, **kwargs) -> Any:
        """Execute async function with circuit breaker protection"""
        if self.state == "OPEN":
            if datetime.now() - self.last_failure_time > timedelta(seconds=self.timeout):
                logger.info("Circuit breaker transitioning to HALF_OPEN state")
                self.state = "HALF_OPEN"
            else:
                raise BotError(
                    f"Circuit breaker OPEN - too many failures",
                    "Service temporarily unavailable due to repeated errors. Please try again in a minute."
                )

        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                logger.info("Circuit breaker transitioning to CLOSED state (recovered)")
                self.state = "CLOSED"
                self.failure_count = 0
            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.now()

            if self.failure_count >= self.failure_threshold:
                logger.error(f"Circuit breaker opening after {self.failure_count} failures")
                self.state = "OPEN"

            raise


# Global circuit breakers for different services
circuit_breakers: Dict[str, CircuitBreaker] = {
    "claude": CircuitBreaker(failure_threshold=5, timeout=60),
    "whisper": CircuitBreaker(failure_threshold=3, timeout=30),
    "twilio": CircuitBreaker(failure_threshold=5, timeout=60),
    "google_api": CircuitBreaker(failure_threshold=5, timeout=60),
}


# Retry Decorator with Exponential Backoff
def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
    circuit_breaker_name: Optional[str] = None
):
    """
    Retry decorator with exponential backoff

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        exponential_base: Base for exponential backoff calculation
        exceptions: Tuple of exceptions to retry on
        circuit_breaker_name: Name of circuit breaker to use
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    # Use circuit breaker if specified
                    if circuit_breaker_name and circuit_breaker_name in circuit_breakers:
                        breaker = circuit_breakers[circuit_breaker_name]
                        return await breaker.call_async(func, *args, **kwargs)
                    else:
                        return await func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        delay = initial_delay * (exponential_base ** attempt)
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {str(e)}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}: {str(e)}"
                        )

            # All retries exhausted
            raise last_exception

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    if circuit_breaker_name and circuit_breaker_name in circuit_breakers:
                        breaker = circuit_breakers[circuit_breaker_name]
                        return breaker.call(func, *args, **kwargs)
                    else:
                        return func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        delay = initial_delay * (exponential_base ** attempt)
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {str(e)}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        import time
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}: {str(e)}"
                        )

            raise last_exception

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


# Error Message Formatter
def format_error_for_user(error: Exception, context: str = "") -> str:
    """
    Convert technical errors to user-friendly messages

    Args:
        error: The exception that occurred
        context: Additional context about what was being done

    Returns:
        User-friendly error message
    """
    if isinstance(error, BotError) and error.user_message:
        return error.user_message

    error_type = type(error).__name__
    error_msg = str(error)

    # Map common errors to user-friendly messages
    error_mappings = {
        "OperationTimeoutError": "⏱️ The request took too long. Please try again.",
        "TimeoutError": "⏱️ The request took too long. Please try again.",  # Python built-in
        "ConnectionError": "🔌 Connection failed. Please check your internet and try again.",
        "HTTPError": "🌐 External service error. Please try again in a moment.",
        "RateLimitError": "⏸️ Too many requests. Please wait a minute and try again.",
        "AuthenticationError": "🔐 Authentication failed. Please contact support.",
        "TranscriptionError": "🎤 Could not transcribe audio. Please try sending text instead.",
        "ImageProcessingError": "🖼️ Could not process image. Try sending a smaller image.",
    }

    # Check for specific error patterns
    if "rate limit" in error_msg.lower() or "429" in error_msg:
        return "⏸️ Rate limit reached. Please wait a moment and try again."

    if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
        return "⏱️ Request timed out. Please try again."

    if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower() or "401" in error_msg:
        return "🔐 Authentication error. Please try again or contact support."

    if "not found" in error_msg.lower() or "404" in error_msg:
        return "❓ Resource not found. Please check your request and try again."

    # Use mapped message if available
    user_message = error_mappings.get(error_type)
    if user_message:
        return user_message

    # Default generic message with context
    if context:
        return f"❌ Error {context}. Please try again or contact support if the issue persists."

    return "❌ Something went wrong. Please try again or contact support if the issue persists."


# Async Context Manager for Error Handling
class ErrorContext:
    """
    Context manager for comprehensive error handling and logging

    Usage:
        async with ErrorContext("processing message", log_errors=True) as ctx:
            # Your code here
            result = await some_function()
            ctx.set_result(result)
    """

    def __init__(self, operation: str, log_errors: bool = True, raise_errors: bool = True):
        self.operation = operation
        self.log_errors = log_errors
        self.raise_errors = raise_errors
        self.result = None
        self.error = None

    async def __aenter__(self):
        logger.info(f"Starting: {self.operation}")
        self.start_time = datetime.now()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds()

        if exc_type is None:
            logger.info(f"✅ Completed: {self.operation} (took {duration:.2f}s)")
            return False

        self.error = exc_val

        if self.log_errors:
            logger.error(
                f"❌ Failed: {self.operation} (took {duration:.2f}s)\n"
                f"Error: {exc_type.__name__}: {str(exc_val)}\n"
                f"Traceback: {traceback.format_exc()}"
            )

        if self.raise_errors:
            return False  # Re-raise the exception

        return True  # Suppress the exception

    def set_result(self, result: Any):
        """Store result for later retrieval"""
        self.result = result


# Validation Helpers
def validate_required_params(params: dict, required_fields: list) -> None:
    """
    Validate that all required parameters are present

    Args:
        params: Dictionary of parameters
        required_fields: List of required field names

    Raises:
        ValueError: If any required field is missing
    """
    missing = [field for field in required_fields if field not in params or params[field] is None]
    if missing:
        raise ValueError(f"Missing required parameters: {', '.join(missing)}")


def validate_image_size(size_bytes: int, max_size_mb: float = 10.0) -> None:
    """
    Validate image size is within limits

    Args:
        size_bytes: Image size in bytes
        max_size_mb: Maximum allowed size in megabytes

    Raises:
        ImageProcessingError: If image is too large
    """
    size_mb = size_bytes / (1024 * 1024)
    if size_mb > max_size_mb:
        raise ImageProcessingError(
            f"Image too large: {size_mb:.2f}MB (max: {max_size_mb}MB)",
            f"Image is too large ({size_mb:.1f}MB). Please send an image smaller than {max_size_mb}MB."
        )


# Health Check Helper
async def check_service_health(service_name: str, check_func: Callable) -> dict:
    """
    Check health of a service

    Args:
        service_name: Name of the service
        check_func: Async function that returns True if healthy

    Returns:
        Dictionary with health status
    """
    try:
        start_time = datetime.now()
        is_healthy = await check_func()
        duration = (datetime.now() - start_time).total_seconds()

        return {
            "service": service_name,
            "healthy": is_healthy,
            "response_time": f"{duration:.3f}s",
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "service": service_name,
            "healthy": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

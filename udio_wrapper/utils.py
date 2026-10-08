import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from udio_wrapper.client import UdioClient

logger = logging.getLogger(__name__)


async def wait_for_token(
    client: "UdioClient",
    task_id: str,
    max_wait_time: int = 300,
    poll_interval: float = 5.0,
) -> "Audio":
    """Poll the API until the audio generation is complete."""
    from udio_wrapper.models.audio import Audio

    start_time = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > max_wait_time:
            raise TimeoutError(
                f"Generation timed out after {max_wait_time}s for task_id={task_id}"
            )

        result = await client._request("GET", f"status/{task_id}")
        status = result.get("status", "unknown")

        logger.debug(f"Polling task {task_id}: status={status}")

        if status == "completed":
            audio_data = result.get("audio", {})
            return Audio(
                task_id=task_id,
                audio_url=audio_data.get("url"),
                lyrics=audio_data.get("lyrics", ""),
                prompt=audio_data.get("prompt", ""),
                duration_seconds=audio_data.get("duration_seconds", 0),
            )
        elif status in ("failed", "error"):
            error_msg = result.get("error", "Unknown error")
            raise RuntimeError(f"Generation failed for task_id={task_id}: {error_msg}")

        await asyncio.sleep(poll_interval)

import asyncio
import argparse
import json
import logging

from udio_wrapper import UdioClient, AudioParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Replace with your session cookie or cookie file path
SESSION_COOKIE = None  # or your cookie string
COOKIE_FILE = None  # or path to cookies.txt
PROXY = None  # or your proxy string, e.g. "http://user:pass@host:port"


async def main():
    client = UdioClient(
        session_cookie=SESSION_COOKIE,
        cookie_file=COOKIE_FILE,
        proxy=PROXY,
    )

    # Test authentication by fetching user info
    logger.info("Fetching user info...")
    user_info = await client.get_user_info()
    logger.info(f"Logged in as: {json.dumps(user_info, indent=2)}")

    # Generate audio
    params = AudioParams(
        prompt="lo-fi hip hop beats to relax to",
        duration_seconds=30,
        style_description="chill, ambient, piano",
    )

    logger.info("Generating audio...")
    audio = await client.generate_audio(params)
    logger.info(f"Generated audio: {json.dumps(audio.to_dict(), indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())

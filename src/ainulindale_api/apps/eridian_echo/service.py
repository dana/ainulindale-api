import asyncio
import contextlib
import logging
import os

from google import genai

from . import models

logger = logging.getLogger(__name__)

# The API key is loaded from the environment variable
# (populated by a Kubernetes Secret in prod/CI)

client = None
with contextlib.suppress(ValueError):
    client = genai.Client()


def _transcribe_sync(filepath: str) -> str:
    """Synchronous function to upload and transcribe using Gemini."""
    logger.info(f"Uploading {filepath}...")
    uploaded_file = client.files.upload(file=filepath)

    try:
        logger.info(f"Generating transcript for {filepath}...")
        prompt = """
        Please provide a highly accurate text transcript of this interview. 
        Carefully distinguish between the two speakers 
        (Label them as 'Local Host' and 'Remote Guest').
        """

        response = client.models.generate_content(
            model="gemini-3.1-pro-preview", contents=[prompt, uploaded_file]
        )
        return response.text
    finally:
        logger.info(f"Cleaning up remote file {uploaded_file.name}...")
        client.files.delete(name=uploaded_file.name)


async def transcribe_mp3(job_id: str, filepath: str):
    """Background task to run the transcription and update the database."""
    try:
        await models.update_job_status(job_id, "processing")

        # Run the synchronous Gemini call in a background thread
        transcript = await asyncio.to_thread(_transcribe_sync, filepath)

        await models.update_job_status(job_id, "succeeded", transcript=transcript)
    except Exception as e:
        logger.exception(f"Transcription failed for job {job_id}")
        await models.update_job_status(job_id, "failed", error=str(e))
    finally:
        # Cleanup the local temporary file
        if os.path.exists(filepath):
            os.remove(filepath)

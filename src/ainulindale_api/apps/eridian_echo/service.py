import asyncio
import base64
import json
import logging
import os
import ssl
import urllib.error
import urllib.request

from google import genai

from . import models

logger = logging.getLogger(__name__)

_client = None


def get_client() -> genai.Client:
    global _client
    if _client is not None:
        return _client

    gemini_key = os.environ.get("GEMINI_API_KEY")

    if not gemini_key:
        # Try fetching from kubernetes secret directly using service account
        token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"  # nosec
        ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

        if os.path.exists(token_path) and os.path.exists(ns_path):
            try:
                with open(token_path) as f:
                    token = f.read().strip()
                with open(ns_path) as f:
                    namespace = f.read().strip()

                base_url = "https://kubernetes.default.svc/api/v1/namespaces"
                url = f"{base_url}/{namespace}/secrets/gemini-api-key"
                context = ssl.create_default_context(cafile=ca_path)
                req = urllib.request.Request(
                    url, headers={"Authorization": f"Bearer {token}"}
                )

                with urllib.request.urlopen(
                    req, context=context, timeout=10
                ) as response:  # nosec
                    data = json.loads(response.read().decode())
                    b64_val = data.get("data", {}).get("GEMINI_API_KEY")
                    if b64_val:
                        os.environ["GEMINI_API_KEY"] = (
                            base64.b64decode(b64_val).decode("utf-8").strip()
                        )
                        logger.info("Loaded GEMINI_API_KEY from Kubernetes secret")
            except Exception as e:
                logger.error(f"Failed to load kubernetes secret: {e}")

    _client = genai.Client()
    return _client


def _transcribe_sync(filepath: str) -> str:
    """Synchronous function to upload and transcribe using Gemini."""
    client = get_client()
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

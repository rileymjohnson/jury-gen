import gzip
import json
import logging

import boto3

# Import logic from the local 'witness_processing.py' file
import witness_processing

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")


def _load_chunks(event_or_chunks):
    if isinstance(event_or_chunks, list):
        return event_or_chunks
    if isinstance(event_or_chunks, dict):
        compression = event_or_chunks.get("Compression")
        s3obj = event_or_chunks.get("S3Object") or event_or_chunks
        if isinstance(s3obj, dict) and "Bucket" in s3obj and "Key" in s3obj:
            obj = s3.get_object(Bucket=s3obj["Bucket"], Key=s3obj["Key"])
            body = obj["Body"].read()
            if compression == "gzip" or s3obj["Key"].endswith(".gz"):
                body = gzip.decompress(body)
            chunks = json.loads(body.decode("utf-8"))
            if not isinstance(chunks, list):
                raise ValueError("Loaded chunks is not a list")
            return chunks
    raise ValueError("Input must be a list of chunks or S3 pointer dict")


def lambda_handler(event, context):
    """
    Extracts witness names from a list of text chunks.

    1. Receives a list of text chunks from the step.
    2. Calls the 'extract_witnesses' function.
    3. Returns the list of extracted witnesses.
    """

    # 1. Get input from the event
    try:
        # The input for this step may be a list or an S3 pointer
        chunks = _load_chunks(event)

    except (TypeError, ValueError) as e:
        logger.error(f"Invalid input event: {e!s}")
        raise ValueError(f"Invalid input: {e!s}") from e

    logger.info(f"Starting witness extraction with {len(chunks)} chunks.")

    # 2. Call the extraction function
    try:
        witness_list = witness_processing.extract_witnesses(chunks)
        logger.info(f"Successfully extracted {len(witness_list)} witnesses.")

    except Exception as e:
        # This will catch any errors from the Bedrock call
        logger.error(f"Failed during witness extraction: {e!s}")
        raise RuntimeError(f"Witness extraction failed: {e!s}") from e

    # 3. Return the result
    return witness_list

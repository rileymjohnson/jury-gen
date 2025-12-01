import gzip
import json
import logging

import boto3

# Import logic from the local 'case_facts_processing.py' file
import case_facts_processing

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")


def _load_chunks(maybe_chunks):
    if isinstance(maybe_chunks, list):
        return maybe_chunks
    if isinstance(maybe_chunks, dict):
        compression = maybe_chunks.get("Compression")
        s3obj = maybe_chunks.get("S3Object") or maybe_chunks
        if isinstance(s3obj, dict) and "Bucket" in s3obj and "Key" in s3obj:
            obj = s3.get_object(Bucket=s3obj["Bucket"], Key=s3obj["Key"])
            body = obj["Body"].read()
            if compression == "gzip" or s3obj["Key"].endswith(".gz"):
                body = gzip.decompress(body)
            chunks = json.loads(body.decode("utf-8"))
            if not isinstance(chunks, list):
                raise ValueError("Loaded chunks is not a list")
            return chunks
    raise ValueError("Invalid chunks input; expected list or S3 pointer dict")


def lambda_handler(event, context):
    """
    Extracts case facts by processing chunks from all documents.

    1. Receives { "complaint_chunks": [...], "answer_chunks": [...],
                   "witness_chunks": [...] } from the step.
    2. Calls the 'extract_case_facts' function.
    3. Returns the final case facts string.
    """

    # 1. Get input from the event
    try:
        # The input for this step is an object containing all chunks
        complaint_chunks = _load_chunks(event.get("complaint_chunks", [])) if event.get("complaint_chunks") is not None else []  # noqa: E501
        answer_chunks = _load_chunks(event.get("answer_chunks", [])) if event.get("answer_chunks") is not None else []
        witness_chunks_val = event.get("witness_chunks")
        witness_chunks = _load_chunks(witness_chunks_val) if witness_chunks_val is not None else []  # Optional

        if not complaint_chunks or not answer_chunks:
            logger.warning("Complaint or Answer chunks are missing. Facts may be incomplete.")

    except (TypeError, KeyError) as e:
        logger.error(f"Invalid input event: {e!s}")
        raise ValueError(f"Invalid input: {e!s}") from e

    logger.info("Starting case facts extraction...")

    # 2. Call the extraction function
    try:
        case_facts_summary = case_facts_processing.extract_case_facts(
            complaint_chunks=complaint_chunks, answer_chunks=answer_chunks, witness_chunks=witness_chunks
        )

        if not case_facts_summary:
            logger.warning("Case facts extraction returned an empty string.")
        else:
            logger.info("Successfully extracted case facts.")

    except Exception as e:
        # This will catch any errors from the Bedrock calls
        logger.error(f"Failed during case facts extraction: {e!s}")
        raise RuntimeError(f"Case facts extraction failed: {e!s}") from e

    # 3. Return the result (a single string)
    return case_facts_summary

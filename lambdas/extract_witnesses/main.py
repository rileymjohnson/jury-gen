import json
import logging
import os

# Import logic from the local 'witness_processing.py' file
import witness_processing

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Extracts witness names from a list of text chunks.
    
    1. Receives a list of text chunks from the step.
    2. Calls the 'extract_witnesses' function.
    3. Returns the list of extracted witnesses.
    """
    
    # 1. Get input from the event
    try:
        # The input for this step is just the list of chunks
        chunks = event
        if not isinstance(chunks, list):
            raise ValueError("Input event must be a list of text chunks.")

    except (TypeError, ValueError) as e:
        logger.error(f"Invalid input event: {str(e)}")
        raise ValueError(f"Invalid input: {str(e)}")

    logger.info(f"Starting witness extraction with {len(chunks)} chunks.")

    # 2. Call the extraction function
    try:
        witness_list = witness_processing.extract_witnesses(chunks)
        logger.info(f"Successfully extracted {len(witness_list)} witnesses.")

    except Exception as e:
        # This will catch any errors from the Bedrock call
        logger.error(f"Failed during witness extraction: {str(e)}")
        raise RuntimeError(f"Witness extraction failed: {str(e)}")

    # 3. Return the result
    return witness_list

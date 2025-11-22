import json
import logging
import os

# Import logic from the local 'case_facts_processing.py' file
import case_facts_processing

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
        complaint_chunks = event.get('complaint_chunks', [])
        answer_chunks = event.get('answer_chunks', [])
        witness_chunks = event.get('witness_chunks', []) # Optional
        
        if not complaint_chunks or not answer_chunks:
             logger.warning("Complaint or Answer chunks are missing. Facts may be incomplete.")

    except (TypeError, KeyError) as e:
        logger.error(f"Invalid input event: {str(e)}")
        raise ValueError(f"Invalid input: {str(e)}")

    logger.info("Starting case facts extraction...")

    # 2. Call the extraction function
    try:
        case_facts_summary = case_facts_processing.extract_case_facts(
            complaint_chunks=complaint_chunks,
            answer_chunks=answer_chunks,
            witness_chunks=witness_chunks
        )
        
        if not case_facts_summary:
            logger.warning("Case facts extraction returned an empty string.")
        else:
            logger.info("Successfully extracted case facts.")

    except Exception as e:
        # This will catch any errors from the Bedrock calls
        logger.error(f"Failed during case facts extraction: {str(e)}")
        raise RuntimeError(f"Case facts extraction failed: {str(e)}")

    # 3. Return the result (a single string)
    return case_facts_summary

import logging

# Import logic from the local 'instruction_processing.py' file
import instruction_processing

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    Generates the final list of jury instructions.

    1. Receives { "claims": [...], "counterclaims": [...], "case_facts": "..." }
    2. Calls the 'generate_instructions' pipeline.
    3. Returns the final list of instruction objects.
    """

    # 1. Get input from the event
    try:
        # The input is an object with all our processed data
        claims = event.get("claims", [])
        counterclaims = event.get("counterclaims", [])
        case_facts = event.get("case_facts", "")
        witnesses = event.get("witnesses", [])
        config = event.get("config")
        if not isinstance(config, dict):
            logger.error("Missing or invalid 'config'")
            raise ValueError("'config' is required and must be an object")

        if not case_facts:
            logger.warning("Case facts are missing. Instructions may be poor.")
        if not claims and not counterclaims:
            logger.error("No claims or counterclaims provided.")
            raise ValueError("Input must contain 'claims' or 'counterclaims'")

    except (TypeError, KeyError, ValueError) as e:
        logger.error(f"Invalid input event: {e!s}")
        raise ValueError(f"Invalid input: {e!s}") from e

    logger.info(f"Starting instruction generation for {len(claims)} claims and {len(counterclaims)} counterclaims.")

    # 2. Call the main generation pipeline
    try:
        instruction_list = instruction_processing.generate_instructions(
            claims=claims, counterclaims=counterclaims, case_facts=case_facts, witnesses=witnesses, config=config
        )

        logger.info(f"Successfully generated {len(instruction_list)} instructions.")

    except Exception as e:
        # This will catch any errors from the Bedrock calls
        logger.error(f"Failed during instruction generation: {e!s}")
        raise RuntimeError(f"Instruction generation failed: {e!s}") from e

    # 3. Return the result
    return instruction_list

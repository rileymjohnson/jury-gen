import json
import logging
import os

# Import logic from the local 'enrichment_processing.py' file
import enrichment_processing

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Enriches a single legal item (claim or counterclaim) with
    its associated damages and defenses.
    
    Designed to be used in a Step Function Map state.
    """
    
    # 1. Get input from the event
    try:
        # The 'item' is the single claim/counterclaim from the Map iterator
        item = event['item'] 
        # 'type' tells us how to process it
        item_type = event['type'] # "claim" or "counterclaim"
        
        # We also get all chunks
        complaint_chunks = event.get('complaint_chunks', [])
        answer_chunks = event.get('answer_chunks', [])
        
        if not item or not item_type:
            raise ValueError("Input event must contain 'item' and 'type'")

    except (TypeError, KeyError, ValueError) as e:
        logger.error(f"Invalid input event: {str(e)}")
        raise ValueError(f"Invalid input: {str(e)}")

    logger.info(f"Enriching {item_type}: {item.get('claim_id', 'Unmatched')}")

    # 2. Build the context string (used in prompts)
    if item.get('claim_id'):
        claim_context = f"Claim ID {item['claim_id']}: {', '.join(item['raw_texts'])}"
    else:
        claim_context = f"Unmatched claim: {', '.join(item['raw_texts'])}"

    # 3. Call processing functions based on type
    try:
        if item_type == "claim":
            # --- For a PLAINTIFF'S CLAIM ---
            
            # 1. Damages are in the COMPLAINT
            logger.info("Extracting damages from complaint chunks...")
            damages = enrichment_processing.extract_damages_for_claim(
                claim_context=claim_context,
                complaint_chunks=complaint_chunks,
                window_size=3,
                claim_type='claims'
            )
            
            # 2. Defenses are in the ANSWER
            logger.info("Extracting defenses from answer chunks...")
            defenses = enrichment_processing.extract_raw_defenses_for_claim(
                claim_context=claim_context,
                answer_chunks=answer_chunks,
                window_size=3
            )
            
        else: # item_type == "counterclaim"
            # --- For a DEFENDANT'S COUNTERCLAIM ---
            
            # 1. Damages are in the ANSWER (with the counterclaim)
            logger.info("Extracting damages from answer chunks...")
            damages = enrichment_processing.extract_damages_for_claim(
                claim_context=claim_context,
                complaint_chunks=answer_chunks, # Pass answer chunks
                window_size=3,
                claim_type='counterclaims'
            )
            
            # 2. Counterclaims don't have defenses (in this workflow)
            defenses = []

    except Exception as e:
        logger.error(f"Failed during enrichment: {str(e)}")
        raise RuntimeError(f"Enrichment pipeline failed: {str(e)}")

    # 4. Return the fully enriched item
    enriched_item = item.copy() # Start with the original item
    enriched_item['damages'] = damages
    enriched_item['defenses'] = defenses
    
    logger.info("Enrichment successful.")
    return enriched_item

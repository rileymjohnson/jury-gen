import boto3
import os
import json
import datetime
import logging
from decimal import Decimal

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')

try:
    TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']
    table = dynamodb.Table(TABLE_NAME)
except KeyError:
    logger.error("DYNAMODB_TABLE_NAME environment variable not set.")
    raise

class DecimalEncoder(json.JSONEncoder):
    """
    Helper class to convert a DynamoDB item to JSON,
    handling Decimal types.
    """
    def default(self, o):
        if isinstance(o, Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)

def lambda_handler(event, context):
    """
    Saves the final results of the jury instruction job.
    
    1. Receives the final, combined state from the Step Function.
    2. Updates the DynamoDB item with all results.
    3. Sets the job status to "COMPLETE".
    """
    
    # The 'event' is the final, aggregated state from the Step Function.
    # We expect it to have all the results we've gathered.
    try:
        job_id = event['jury_instruction_id']
        
        # We use .get() for optional fields, providing a default
        # to avoid errors if a branch didn't run or produced
        # no results (e.g., no counterclaims).
        case_facts = event.get('case_facts', '')
        witnesses = event.get('witnesses', [])
        claims = event.get('claims', [])
        counterclaims = event.get('counterclaims', [])
        instructions = event.get('instructions', [])

        if not job_id:
            raise KeyError("Input event must contain 'jury_instruction_id'")

    except (TypeError, KeyError) as e:
        logger.error(f"Invalid input event. Missing required keys: {str(e)}")
        raise ValueError(f"Invalid input event: {str(e)}")

    completed_at = datetime.datetime.utcnow().isoformat()

    try:
        logger.info(f"Saving results for completed job {job_id}...")
        
        # We will update the existing item in DynamoDB.
        # This adds all the new fields and sets the status to COMPLETE.
        update_expression = (
            "SET #status = :s, "
            "#completedAt = :ca, "
            "#case_facts = :cf, "
            "#witnesses = :w, "
            "#claims = :c, "
            "#counterclaims = :cc, "
            "#jury_instructions_text = :ji"
        )
        
        expression_attribute_names = {
            '#status': 'status',
            '#completedAt': 'completedAt',
            '#case_facts': 'case_facts',
            '#witnesses': 'witnesses',
            '#claims': 'claims',
            '#counterclaims': 'counterclaims',
            '#jury_instructions_text': 'jury_instructions_text'
        }
        
        expression_attribute_values = {
            ':s': 'COMPLETE',
            ':ca': completed_at,
            ':cf': case_facts,
            ':w': witnesses,
            ':c': claims,
            ':cc': counterclaims,
            ':ji': instructions
        }

        # We must use json.loads(json.dumps(..., cls=DecimalEncoder))
        # to handle any potential Decimal types if we were reading
        # from DynamoDB, but for writing Python objects, this is
        # generally fine. Boto3 handles the Python-to-DynamoDB
        # type conversion for us.
        
        table.update_item(
            Key={'jury_instruction_id': job_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values
        )
        
        logger.info(f"Successfully saved results for job {job_id}.")
        
        # Return a success message
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Job completed successfully',
                'jury_instruction_id': job_id
            })
        }

    except Exception as e:
        logger.error(f"Error saving results for job {job_id}.")
        logger.error(str(e))
        # This will fail the Lambda and the Step Function execution
        raise RuntimeError(f"DynamoDB update_item failed: {str(e)}")

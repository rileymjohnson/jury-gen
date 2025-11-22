import json
import logging
import os
import boto3
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')

TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
if not TABLE_NAME:
    raise RuntimeError("Missing env var DYNAMODB_TABLE_NAME")

table = dynamodb.Table(TABLE_NAME)


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        return super().default(o)


def _response(status_code: int, body: dict):
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body, cls=DecimalEncoder),
    }


def lambda_handler(event, context):
    try:
        # Expect GET /jury/status/{id} via API Gateway proxy
        path_params = event.get('pathParameters') or {}
        job_id = path_params.get('id') or path_params.get('job_id')
        if not job_id:
            return _response(400, {'error': "Missing job id in path"})

        res = table.get_item(Key={'jury_instruction_id': job_id})
        item = res.get('Item')
        if not item:
            return _response(404, {'error': 'Not found'})

        return _response(200, item)
    except Exception as e:
        logger.exception("Failed to fetch job status")
        return _response(500, {'error': f'Failed to fetch status: {e}'})


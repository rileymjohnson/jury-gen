import base64
from io import BytesIO
import json
import logging
import os

import boto3
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Inches, Pt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME")
if not TABLE_NAME:
    raise RuntimeError("Missing env var DYNAMODB_TABLE_NAME")
table = dynamodb.Table(TABLE_NAME)


def _response(status_code: int, body: dict, *, headers: dict | None = None):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }


def build_docx(instructions: list[dict], party_type: str) -> bytes:
    document = Document()

    for section in document.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    for i, instruction in enumerate(instructions):
        jury_instruction_item_number_paragraph = document.add_paragraph(
            f'{party_type}’S REQUESTED JURY INSTRUCTION NO. {i + 1}\n'  # noqa: RUF001
        )

        run = jury_instruction_item_number_paragraph.runs[0]
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)
        run.font.bold = True

        jury_instruction_title_paragraph = document.add_paragraph(instruction['title'].upper())
        jury_instruction_title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        run = jury_instruction_title_paragraph.runs[0]
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)
        run.font.bold = True

        jury_instruction_content_paragraph = document.add_paragraph(instruction['customized_text'])

        run = jury_instruction_content_paragraph.runs[0]
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)

        if instruction['number'].startswith('CUSTOM-DEFAMATION-'):
            instruction_number = f'Custom Jury Instruction {instruction["number"]}'
        else:
            instruction_number = f'Florida Standard Jury Instruction {instruction["number"]}'

        jury_instruction_number_paragraph = document.add_paragraph(instruction_number)

        run = jury_instruction_number_paragraph.runs[0]
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)
        run.font.italic = True

        jury_instruction_status_paragraph = document.add_paragraph('''
Granted ___________
Denied ___________
Withdrawn ___________'''.strip())

        run = jury_instruction_status_paragraph.runs[0]
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)

        run.add_break(WD_BREAK.PAGE)

    out = BytesIO()
    document.save(out)
    return out.getvalue()


def lambda_handler(event, context):
    try:
        path_params = event.get("pathParameters") or {}
        job_id = path_params.get("id") or path_params.get("job_id")
        if not job_id:
            return _response(400, {"error": "Missing id in path"})

        res = table.get_item(Key={"jury_instruction_id": job_id})
        item = res.get("Item")
        if not item:
            return _response(404, {"error": "Record not found"})

        status = item.get("status")
        if status != "COMPLETE":
            return _response(409, {"error": f"Record is not complete (status={status})"})

        # Log party_type from saved config for downstream usage/inspection
        cfg = item.get("config") or {}
        party_type = str(cfg.get("party_type", "")).upper() if isinstance(cfg, dict) else ""

        instructions = item.get("jury_instructions_text") or []
        if not isinstance(instructions, list):
            return _response(500, {"error": "Invalid instructions format"})

        docx_bytes = build_docx(instructions, party_type)
        b64 = base64.b64encode(docx_bytes).decode("ascii")

        filename = f"JuryInstructions-{job_id}.docx"
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "Content-Disposition": f"attachment; filename=\"{filename}\"",
            },
            "isBase64Encoded": True,
            "body": b64,
        }
    except Exception as e:
        logger.exception("Failed to generate docx")
        return _response(500, {"error": f"Failed to generate document: {e}"})

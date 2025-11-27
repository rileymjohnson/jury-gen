import json
import os

import boto3

bedrock = boto3.client("bedrock-runtime")

# DynamoDB tables from env
_CLAIMS_TABLE = os.environ.get("DYNAMODB_CLAIMS_TABLE_NAME", "Claims")
_SJI_TABLE = os.environ.get("DYNAMODB_STANDARD_JURY_INSTRUCTIONS_TABLE_NAME", "StandardJuryInstructions")
_ddb = boto3.resource("dynamodb")
_claims_table = _ddb.Table(_CLAIMS_TABLE)
_sji_table = _ddb.Table(_SJI_TABLE)


def _scan_all(table, filter_expression=None):
    kwargs = {}
    if filter_expression:
        kwargs["FilterExpression"] = filter_expression
    items = []
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


# Cache database claims at cold start (small reference set)
database_claims = _scan_all(_claims_table)


def database_get_claim_by_id(claim_id):
    try:
        resp = _claims_table.get_item(Key={"id": claim_id})
        item = resp.get("Item")
        if item:
            return item
    except Exception:
        pass
    # Fallback to in-memory cache
    matches = [c for c in database_claims if c.get("id") == claim_id]
    return matches[0] if matches else None


def match_claim_to_category(claim_title, case_facts, standard_categories):
    """
    Match a claim to a standard jury instruction category or determine if custom needed

    Args:
        claim_title: Title of the claim (e.g., "Breach of Contract")
        case_facts: 2-3 paragraph case facts summary
        standard_categories: List of tuples [(category_number, category_title), ...]

    Returns:
        str: Category number (e.g., "416") or "CUSTOM"
    """

    # Format categories for the prompt
    categories_list = "\n".join([f"{num}: {title}" for num, title in standard_categories])

    tools = [
        {
            "name": "match_category",
            "description": "Match claim to instruction category or indicate custom needed",
            "input_schema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "The category number (e.g., '416') or 'CUSTOM' if no match",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief explanation of why this category matches or why custom is needed",
                    },
                },
                "required": ["category", "reasoning"],
            },
        }
    ]

    prompt = f"""Match this claim to the appropriate standard jury instruction category.

CLAIM: {claim_title}

CASE FACTS:
{case_facts}

AVAILABLE INSTRUCTION CATEGORIES:
{categories_list}

Determine which category this claim belongs to. If the claim clearly matches one of the standard categories, return that category number. If there is no good match (e.g., claims like "Conversion", "Libel", "Slander", "Defamation" that aren't listed), return "CUSTOM".

Consider:
- The claim title itself
- The nature of the claim based on case facts
- Whether it's a tort vs. contract claim
- Whether it fits clearly within a standard category"""  # noqa: E501

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "match_category"},
            "messages": [{"role": "user", "content": prompt}],
        }
    )

    response = bedrock.invoke_model(
        body=body,
        modelId="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        accept="application/json",
        contentType="application/json",
    )

    response_body = json.loads(response.get("body").read())

    # Extract tool use result
    for item in response_body.get("content", []):
        if item.get("type") == "tool_use":
            result = item["input"]
            print(f"Claim '{claim_title}' matched to: {result['category']}")
            print(f"Reasoning: {result['reasoning']}")
            return result["category"]

    # Fallback
    return "CUSTOM"


def llm_select_instructions(claim_title, claim_elements, defenses, case_facts, available_instructions):
    """
    LLM selects which instructions to include and returns customized versions
    """

    instructions_list = json.dumps(available_instructions, indent=2)
    defenses_list = "\n".join([f"- {d['name']}: {d['raw_text']}" for d in defenses])
    elements_list = "\n".join([f"- {elem}" for elem in claim_elements])

    tools = [
        {
            "name": "select_instructions",
            "description": "Select which jury instructions apply and customize them",
            "input_schema": {
                "type": "object",
                "properties": {
                    "selected_instructions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "number": {"type": "string", "description": "Instruction number (e.g., '416.5')"},
                                "include": {"type": "boolean", "description": "Whether to include this instruction"},
                                "reasoning": {
                                    "type": "string",
                                    "description": "Why this instruction should or should not be included",
                                },
                                "customized_text": {
                                    "type": "string",
                                    "description": "The fully customized instruction text with bracketed choices resolved and party names filled in. Only provide if include=true.",  # noqa: E501
                                },
                            },
                            "required": ["number", "include", "reasoning"],
                        },
                    }
                },
                "required": ["selected_instructions"],
            },
        }
    ]

    prompt = f"""You are selecting and customizing jury instructions for a specific claim.

CLAIM: {claim_title}

CLAIM ELEMENTS (what must be proven):
{elements_list}

DEFENSES RAISED:
{defenses_list}

CASE FACTS:
{case_facts}

AVAILABLE INSTRUCTIONS:
{instructions_list}

For EACH instruction, determine:
1. Should it be included? Consider:
   - Is this element/issue contested in the case?
   - Do the defenses raise this issue?
   - Does it apply to the facts?
   - Do the notes_on_use say when to include/exclude?

2. If included, provide the CUSTOMIZED text:
   - Choose appropriate bracketed alternatives
   - Fill in party names from case facts
   - Fill in any other blanks (amounts, dates, etc.)
   - Remove unused bracketed options

Example for 416.5:
- Original: "[Contracts may be written or oral.] [Contracts may be partly written and partly oral.] Oral contracts are just as valid as written contracts."
- If oral contract: "Contracts may be written or oral. Oral contracts are just as valid as written contracts."
- If mixed: "Contracts may be partly written and partly oral. Oral contracts are just as valid as written contracts."
- If fully written: Don't include this instruction at all

Be thorough but conservative - only include instructions that are truly relevant."""  # noqa: E501

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "select_instructions"},
            "messages": [{"role": "user", "content": prompt}],
        }
    )

    response = bedrock.invoke_model(
        body=body,
        modelId="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        accept="application/json",
        contentType="application/json",
    )

    response_body = json.loads(response.get("body").read())

    # Extract tool use result
    for item in response_body.get("content", []):
        if item.get("type") == "tool_use":
            all_instructions = item["input"]["selected_instructions"]
            # Filter to only included ones
            selected = [inst for inst in all_instructions if inst["include"]]
            return selected

    return []


def select_and_customize_instructions(category_number, claim, claim_elements, defenses, case_facts):
    """
    Select which sub-instructions from a category apply and customize them

    Args:
        category_number: e.g., "416"
        claim: Claim object from litigation guide
        claim_elements: List of elements for this claim type
        defenses: List of defense dicts with 'name' and 'raw_text'
        case_facts: Case facts summary

    Returns:
        List of dicts with instruction details and customization args
    """

    # Get all sub-instructions in this category
    # Scan and filter by category_number, then sort by number
    # (Consider adding a GSI on category_number if this grows.)
    from boto3.dynamodb.conditions import Attr

    sub_instructions = _sji_table.scan(FilterExpression=Attr("category_number").eq(category_number)).get("Items", [])
    sub_instructions = sorted(sub_instructions, key=lambda x: str(x.get("number", "")))

    # Format for LLM
    instructions_summary = [{
        "number": inst.get("number"),
        "title": inst.get("title"),
        "main_paragraph": inst.get("main_paragraph"),
        "notes_on_use": inst.get("notes_on_use") or [],
    } for inst in sub_instructions]

    # Ask LLM to select which ones apply
    selected = llm_select_instructions(
        claim_title=claim.get("title"),
        claim_elements=claim_elements,
        defenses=defenses,
        case_facts=case_facts,
        available_instructions=instructions_summary,
    )

    return selected


def generate_custom_instructions(claim_info, claim, case_facts):
    """
    Generate custom jury instructions for claims without standard instructions

    Args:
        claim_info: Dict with claim data (raw_texts, damages, defenses)
        claim: Claim object from litigation guide (with elements, description)
        case_facts: Case facts summary

    Returns:
        List of instruction dicts with customized_text and reasoning
    """
    print("claim", list(claim.keys()))

    defenses_list = "\n".join([f"- {d['name']}: {d['raw_text']}" for d in claim_info.get("defenses", [])])

    elements_list = "\n".join([f"- {elem}" for elem in claim.get("elements", [])])

    tools = [
        {
            "name": "generate_custom_instructions",
            "description": "Generate custom jury instructions for a claim without standard instructions",
            "input_schema": {
                "type": "object",
                "properties": {
                    "instructions": {
                        "type": "array",
                        "description": "List of custom instructions for this claim",
                        "items": {
                            "type": "object",
                            "properties": {
                                "customized_text": {
                                    "type": "string",
                                    "description": \
                                        "The full text of this instruction with party names and facts filled in",
                                },
                                "reasoning": {
                                    "type": "string",
                                    "description": "Brief explanation of what this instruction covers",
                                },
                            },
                            "required": ["customized_text", "reasoning"],
                        },
                    }
                },
                "required": ["instructions"],
            },
        }
    ]

    prompt = f"""Generate custom jury instructions for a claim that has no standard Florida instruction.

CLAIM: {claim.get('title')}

CLAIM ELEMENTS (from Florida Litigation Guide):
{elements_list}

CLAIM DESCRIPTION:
{claim.get('description') or 'No description available'}

DEFENSES RAISED:
{defenses_list}

CASE FACTS:
{case_facts}

Generate a complete set of jury instructions for this claim, following the style and structure of Florida Standard Jury Instructions. You should generate multiple separate instructions covering:

1. Introduction to the claim - Brief statement of what claimant alleges
2. Essential elements - What claimant must prove (numbered list based on claim elements above)
3. Any key definitions needed
4. Issues the jury must decide
5. Burden of proof - what happens if claim not proven
6. Defense instructions - for each defense raised
7. Burden if claim proven - what jury should do next

Use neutral, clear language. Fill in actual party names from case facts. Model after standard instructions in the 401.x and 416.x series.

Example formats:
- Introduction: "(Claimant) claims that (defendant) committed [tort/wrong] by [describe actions]..."
- Elements: "To prove [claim], (claimant) must prove all of the following: 1. [element]; 2. [element]; 3. [element]..."
- Issues: "The issues you must decide on (claimant)'s claim against (defendant) are whether [list issues]..."
- Burden: "If the greater weight of the evidence does not support (claimant)'s claim, your verdict should be for (defendant)."

Each instruction should be a separate item in the array."""  # noqa: E501

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "generate_custom_instructions"},
            "messages": [{"role": "user", "content": prompt}],
        }
    )

    response = bedrock.invoke_model(
        body=body,
        modelId="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        accept="application/json",
        contentType="application/json",
    )

    response_body = json.loads(response.get("body").read())

    # Extract tool use result
    for item in response_body.get("content", []):
        if item.get("type") == "tool_use":
            instructions = item["input"]["instructions"]
            # Add number field for consistency with standard instructions
            for i, inst in enumerate(instructions, 1):
                title = (claim.get("title") or "").upper().replace(" ", "-")
                inst["number"] = f"CUSTOM-{title}-{i}"
                inst["claim_description"] = claim.get("description")
                inst["claim_elements"] = claim.get("elements")
            return instructions

    return []


def generate_instructions(claims, counterclaims, case_facts):
    all_400_instructions = []

    custom_claims = []
    custom_counterclaims = []

    # Load unique (category_number, category_title) pairs from DynamoDB
    _all_sji = _scan_all(_sji_table)
    standard_instruction_categories = sorted(
        {
            (r.get("category_number"), r.get("category_title"))
            for r in _all_sji
            if r.get("category_number") and r.get("category_title")
        }
    )

    for claim_info in claims:
        claim = database_get_claim_by_id(claim_info["claim_id"])

        if claim is None:
            continue

        category = match_claim_to_category(
            claim_title=claim.get("title"), case_facts=case_facts, standard_categories=standard_instruction_categories
        )

        if category != "CUSTOM":
            selected_instructions = select_and_customize_instructions(
                category_number=category,
                claim=claim,
                claim_elements=claim.get("elements"),
                defenses=claim_info.get("defenses", []),
                case_facts=case_facts,
            )
            all_400_instructions.extend(selected_instructions)
        else:
            custom_claims.append(claim_info)

    for counterclaim_info in counterclaims:
        claim = database_get_claim_by_id(counterclaim_info["claim_id"])

        if claim is None:
            continue

        category = match_claim_to_category(
            claim_title=claim.get("title"), case_facts=case_facts, standard_categories=standard_instruction_categories
        )

        if category != "CUSTOM":
            selected_instructions = select_and_customize_instructions(
                category_number=category,
                claim=claim,
                claim_elements=claim.get("elements"),
                defenses=[],  # Counterclaims don't have defenses from plaintiff
                case_facts=case_facts,
            )
            all_400_instructions.extend(selected_instructions)
        else:
            custom_counterclaims.append(counterclaim_info)

    all_custom_claims = custom_claims + custom_counterclaims

    for claim_info in all_custom_claims:
        claim = database_get_claim_by_id(claim_info["claim_id"])

        custom_instructions = generate_custom_instructions(claim_info=claim_info, claim=claim, case_facts=case_facts)
        all_400_instructions.extend(custom_instructions)

    return all_400_instructions

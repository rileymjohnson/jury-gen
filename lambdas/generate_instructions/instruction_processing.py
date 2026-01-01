import json
import os

import boto3
from boto3.dynamodb.conditions import Attr

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

    print('claim_title', claim_title)
    print('case_facts', case_facts)
    print('standard_categories', standard_categories)

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
    sub_instructions = _sji_table.scan(FilterExpression=Attr("category_number").eq(category_number)).get("Items", [])
    sub_instructions = sorted(sub_instructions, key=lambda x: str(x.get("number", "")))

    # Format for LLM
    instructions_summary = [
        {
            "number": inst.get("number"),
            "title": inst.get("title"),
            "main_paragraph": inst.get("main_paragraph"),
            "notes_on_use": inst.get("notes_on_use") or [],
        }
        for inst in sub_instructions
    ]

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
                                    "description": "The full text of this instruction with party names and facts filled in",  # noqa: E501
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


def _get_instruction_by_number(number: str):
    """Fetch a single standard instruction by its number (e.g., '201.1')."""
    try:
        resp = _sji_table.scan(FilterExpression=Attr("number").eq(number))
        items = resp.get("Items", [])
        if items:
            # In case of multiple versions, pick the one with matching number and first in list
            return items[0]
    except Exception:
        pass
    return None


def _llm_render_instruction(
    template_text: str,
    inputs: dict,
    render_hint: str | None = None,
    extra_instructions: str | None = None,
) -> str:
    """Ask Bedrock to render a filled instruction from a template and inputs.

    render_hint may constrain the output (e.g., 'pre-oath' or 'post-oath').
    """
    tools = [
        {
            "name": "render_instruction",
            "description": "Fill a Florida SJI template with provided inputs; return finalized text",
            "input_schema": {
                "type": "object",
                "properties": {
                    "customized_text": {
                        "type": "string",
                        "description": "The final instruction text with placeholders filled and brackets resolved",
                    }
                },
                "required": ["customized_text"],
            },
        }
    ]

    # Keep prompt explicit to preserve SJI style
    hint_text = ""
    if render_hint == "pre-oath":
        hint_text = (
            "Output only the pre-oath portion that culminates in the oath being administered. "
            "End the output with the sentence about administering the oath."
        )
    elif render_hint == "post-oath":
        hint_text = (
            "Output only the continuation that follows the oath, beginning with the post-oath language."
        )
    elif render_hint == "201.2":
        hint_text = (
            "Resolve bracketed pronouns for each role using the provided pronouns. "
            "Include or omit the self-represented (pro se) paragraphs based on inputs. "
            "Include the uninsured/underinsured motorist carrier paragraph only if has_uim_carrier is true and fill in the carrier name. "  # noqa: E501
            "If electronic_device_policy is provided, apply the corresponding admonition if present in the template. "
            "If permitted_ex_parte_communications are provided, reflect them as appropriate in the communications guidance."  # noqa: E501
        )

    prompt = f"""You are producing a finalized Florida Standard Jury Instruction by resolving a provided template.

TEMPLATE:
{template_text}

INPUTS (JSON):
{json.dumps(inputs, indent=2)}

Instructions:
- Keep the structure and language of the template.
- Replace parenthetical placeholders like (date), (location), and similar with provided values.
- Where the template says to insert a brief description of claims/defenses, write a single clear sentence suitable for voir dire using the case_facts and party names.
- Resolve bracketed alternatives [like this] to the most appropriate single choice; remove unused brackets entirely.
- If the template includes "[I] [The clerk] will now administer your oath.", choose "I" when inputs.oath_administered_by == "judge" and choose "The clerk" when inputs.oath_administered_by == "clerk".
- List principal witnesses as full names separated by commas if provided.
- Do not add extra commentary or headings. Output only the final instruction text.
 {hint_text}
 {extra_instructions or ''}
"""  # noqa: E501

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "render_instruction"},
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
    for item in response_body.get("content", []):
        if item.get("type") == "tool_use":
            return item["input"].get("customized_text", "")
    return ""


def _generate_201_1(config: dict, case_facts: str, witnesses: list[dict]):
    inst = _get_instruction_by_number("201.1")
    if not inst:
        return None

    # Prepare inputs
    witness_names = []
    for w in witnesses or []:
        first = (w or {}).get("first_name") or ""
        last = (w or {}).get("last_name") or ""
        name = (first + " " + last).strip()
        if name:
            witness_names.append(name)

    inputs = {
        "case_facts": case_facts or "",
        "plaintiff_name": config.get("plaintiff_name"),
        "defendant_name": config.get("defendant_name"),
        "incident_date": config.get("incident_date"),
        "incident_location": config.get("incident_location"),
        "additional_voir_dire_info": config.get("additional_voir_dire_info"),
        "principal_witnesses": witness_names,
        "oath_administered_by": (config.get("oath_administered_by") or "clerk").lower(),
    }

    # If oath will be administered, render pre/post segments; otherwise render a single combined instruction
    include_oath = bool(config.get("include_so_help_you_god", False))

    results = []
    if include_oath:
        pre_text = _llm_render_instruction(
            template_text=inst.get("main_paragraph", ""), inputs=inputs, render_hint="pre-oath"
        )
        post_text = _llm_render_instruction(
            template_text=inst.get("main_paragraph", ""), inputs=inputs, render_hint="post-oath"
        )
        if pre_text:
            results.append(
                {
                    "number": inst.get("number"),
                    "title": inst.get("title"),
                    "customized_text": pre_text,
                    "meta": {"is_continuation_part": False},
                }
            )
        if post_text:
            results.append(
                {
                    "number": inst.get("number"),
                    "title": inst.get("title"),
                    "customized_text": post_text,
                    "meta": {"is_continuation_part": True},
                }
            )
    else:
        combined = _llm_render_instruction(template_text=inst.get("main_paragraph", ""), inputs=inputs)
        if combined:
            results.append(
                {
                    "number": inst.get("number"),
                    "title": inst.get("title"),
                    "customized_text": combined,
                    "meta": {"is_continuation_part": False},
                }
            )

    return results if results else None


def _pronouns_for(gender: str | None) -> dict:
    g = (gender or "neutral").lower()
    if g == "male":
        return {"subject": "he", "object": "him", "possessive_adj": "his", "reflexive": "himself"}
    if g == "female":
        return {"subject": "she", "object": "her", "possessive_adj": "her", "reflexive": "herself"}
    # default neutral
    return {"subject": "they", "object": "them", "possessive_adj": "their", "reflexive": "themself"}


def _generate_201_2(config: dict):
    inst = _get_instruction_by_number("201.2")
    if not inst:
        return None

    inputs = {
        "judge_name": config.get("judge_name"),
        "plaintiff_name": config.get("plaintiff_name"),
        "defendant_name": config.get("defendant_name"),
        "plaintiff_attorney_name": config.get("plaintiff_attorney_name"),
        "plaintiff_attorney_pronouns": _pronouns_for(config.get("plaintiff_attorney_gender")),
        "defendant_attorney_name": config.get("defendant_attorney_name"),
        "defendant_attorney_pronouns": _pronouns_for(config.get("defendant_attorney_gender")),
        "court_clerk_name": config.get("court_clerk_name"),
        "court_clerk_pronouns": _pronouns_for(config.get("court_clerk_gender")),
        "court_reporter_name": config.get("court_reporter_name"),
        "court_reporter_pronouns": _pronouns_for(config.get("court_reporter_gender")),
        "bailiff_name": config.get("bailiff_name"),
        "bailiff_pronouns": _pronouns_for(config.get("bailiff_gender")),
        "plaintiff_is_pro_se": bool(config.get("plaintiff_is_pro_se", False)),
        "defendant_is_pro_se": bool(config.get("defendant_is_pro_se", False)),
        "has_uim_carrier": bool(config.get("has_uim_carrier", False)),
        "uim_carrier_name": config.get("uim_carrier_name"),
        "electronic_device_policy": config.get("electronic_device_policy"),
        "permitted_ex_parte_communications": config.get("permitted_ex_parte_communications", []),
    }

    extra = (
        "When resolving bracketed pronouns like [His] [Her] or [he] [she], use the provided *_pronouns fields. "
        "If plaintiff_is_pro_se is true, include the pro se plaintiff paragraph and omit the counsel paragraph. "
        "If defendant_is_pro_se is true, include the pro se defendant paragraph and omit the counsel paragraph. "
        "Include the uninsured/underinsured motorist carrier paragraph only if has_uim_carrier is true, and insert uim_carrier_name. "  # noqa: E501
        "If electronic_device_policy is 'A' or 'B', choose the corresponding policy if present. "
        "If permitted_ex_parte_communications is non-empty, incorporate those topics where the template allows."
    )

    text = _llm_render_instruction(
        template_text=inst.get("main_paragraph", ""), inputs=inputs, render_hint="201.2", extra_instructions=extra
    )
    if not text:
        return None
    return {
        "number": inst.get("number"),
        "title": inst.get("title"),
        "customized_text": text,
    }


def _generate_201_3():
    inst = _get_instruction_by_number("201.3")
    if not inst:
        return None

    # No dynamic inputs needed; let LLM resolve any bracketed variants.
    text = _llm_render_instruction(template_text=inst.get("main_paragraph", ""), inputs={})
    if not text:
        return None
    return {
        "number": inst.get("number"),
        "title": inst.get("title"),
        "customized_text": text,
    }


def _generate_101_1(config: dict):
    inst = _get_instruction_by_number("101.1")
    if not inst:
        return None

    inputs = {
        "include_so_help_you_god": bool(config.get("include_so_help_you_god", False)),
    }

    text = _llm_render_instruction(template_text=inst.get("main_paragraph", ""), inputs=inputs)
    if not text:
        return None
    return {
        "number": inst.get("number"),
        "title": inst.get("title"),
        "customized_text": text,
    }


def _generate_601_1():
    inst = _get_instruction_by_number("601.1")
    if not inst:
        return None

    text = _llm_render_instruction(template_text=inst.get("main_paragraph", ""), inputs={})
    if not text:
        return None
    return {
        "number": inst.get("number"),
        "title": inst.get("title"),
        "customized_text": text,
    }


def _generate_601_2(config: dict | None = None):
    """Believability of witnesses (combined a + optional expert section).

    Include expert-witness guidance only when config.has_expert_witnesses is true.
    """
    inst = _get_instruction_by_number("601.2")
    if not inst:
        return None

    cfg = config or {}
    inputs = {"has_expert_witnesses": bool(cfg.get("has_expert_witnesses", False))}
    extra = (
        "If has_expert_witnesses is false, omit the expert witness subsection (part b) entirely, "
        "including any bracketed expert-introduction sentences. If true, include part b."
    )
    text = _llm_render_instruction(
        template_text=inst.get("main_paragraph", ""), inputs=inputs, extra_instructions=extra
    )
    if not text:
        return None
    return {
        "number": inst.get("number"),
        "title": inst.get("title"),
        "customized_text": text,
    }


def _generate_601_3(config: dict):
    """Official English translation/interpretation — include only when applicable."""
    if not bool(config.get("has_foreign_language_witnesses", False)):
        return None
    inst = _get_instruction_by_number("601.3")
    if not inst:
        return None

    # If a language is known in future, it can be supplied via inputs (e.g., language_used)
    text = _llm_render_instruction(template_text=inst.get("main_paragraph", ""), inputs={})
    if not text:
        return None
    return {
        "number": inst.get("number"),
        "title": inst.get("title"),
        "customized_text": text,
    }


def _generate_601_4(claims: list[dict], counterclaims: list[dict]):
    """Multiple claims — include when there is more than one claim overall.

    Let Bedrock adapt the template language based on claim titles; avoid
    manually injecting the '(state the number)' replacement here.
    """
    total = len(claims or []) + len(counterclaims or [])
    if total <= 1:
        return None
    inst = _get_instruction_by_number("601.4")
    if not inst:
        return None

    # Collect claim titles where available (optional context for the model)
    names: list[str] = []
    for ci in (claims or []):
        c = database_get_claim_by_id(ci.get("claim_id")) if isinstance(ci, dict) else None
        t = (c or {}).get("title")
        if isinstance(t, str) and t.strip():
            names.append(t.strip())
    for ci in (counterclaims or []):
        c = database_get_claim_by_id(ci.get("claim_id")) if isinstance(ci, dict) else None
        t = (c or {}).get("title")
        if isinstance(t, str) and t.strip():
            names.append(t.strip())

    inputs = {"claim_titles": names}
    text = _llm_render_instruction(template_text=inst.get("main_paragraph", ""), inputs=inputs)
    if not text:
        return None
    return {
        "number": inst.get("number"),
        "title": inst.get("title"),
        "customized_text": text,
    }


def _generate_601_5(config: dict):
    """Concluding instruction (before final argument).

    Include when final_instructions_timing == 'before_final_argument'.
    """
    timing = (config or {}).get("final_instructions_timing")
    if str(timing or "").lower() != "before_final_argument":
        return None
    inst = _get_instruction_by_number("601.5")
    if not inst:
        return None

    text = _llm_render_instruction(template_text=inst.get("main_paragraph", ""), inputs={})
    if not text:
        return None
    return {
        "number": inst.get("number"),
        "title": inst.get("title"),
        "customized_text": text,
    }


def generate_instructions(claims, counterclaims, case_facts, witnesses=None, config=None):  # noqa: PLR0912, PLR0915
    # Config can carry toggles and metadata for 100/200/600 series, etc.
    if not isinstance(config, dict):
        config = {}
    witnesses = witnesses or []

    all_instructions = []

    # 201.1 (pre), 101.1 (if enabled), 201.1 (post)
    try:
        parts_201_1 = _generate_201_1(config=config, case_facts=case_facts, witnesses=witnesses)
        if parts_201_1:
            include_oath = bool(config.get("include_so_help_you_god", False))
            pre = [x for x in parts_201_1 if not (x.get("meta") or {}).get("is_continuation_part")]
            post = [x for x in parts_201_1 if (x.get("meta") or {}).get("is_continuation_part")]

            if include_oath:
                # Expect at most one pre and one post; add in sequence with oath between
                all_instructions.extend(pre)
                oath = _generate_101_1(config=config)
                if oath:
                    all_instructions.append(oath)
                all_instructions.extend(post)
            else:
                # No oath; just add whatever 201.1 returned (likely a single combined instruction)
                all_instructions.extend(parts_201_1)
    except Exception:
        # Don't fail the whole job if 201.1/101.1 generation fails
        pass

    # 201.2 Introduction of Participants and Their Roles
    try:
        inst_201_2 = _generate_201_2(config=config)
        if inst_201_2:
            all_instructions.append(inst_201_2)
    except Exception:
        pass

    # 201.3
    try:
        inst_201_3 = _generate_201_3()
        if inst_201_3:
            all_instructions.append(inst_201_3)
    except Exception:
        pass

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
            all_instructions.extend(selected_instructions)
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
            all_instructions.extend(selected_instructions)
        else:
            custom_counterclaims.append(counterclaim_info)

    all_custom_claims = custom_claims + custom_counterclaims

    for claim_info in all_custom_claims:
        claim = database_get_claim_by_id(claim_info["claim_id"])

        custom_instructions = generate_custom_instructions(claim_info=claim_info, claim=claim, case_facts=case_facts)
        all_instructions.extend(custom_instructions)

    # 600-series concluding instructions
    try:
        si_601_1 = _generate_601_1()
        if si_601_1:
            all_instructions.append(si_601_1)
    except Exception:
        pass

    try:
        si_601_2 = _generate_601_2(config=config)
        if si_601_2:
            all_instructions.append(si_601_2)
    except Exception:
        pass

    try:
        si_601_3 = _generate_601_3(config=config)
        if si_601_3:
            all_instructions.append(si_601_3)
    except Exception:
        pass

    try:
        si_601_4 = _generate_601_4(claims=claims, counterclaims=counterclaims)
        if si_601_4:
            all_instructions.append(si_601_4)
    except Exception:
        pass

    try:
        si_601_5 = _generate_601_5(config=config)
        if si_601_5:
            all_instructions.append(si_601_5)
    except Exception:
        pass

    return all_instructions

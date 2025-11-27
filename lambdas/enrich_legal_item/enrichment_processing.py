import json

import boto3

bedrock = boto3.client("bedrock-runtime")


def process_defense_window(claim_context: str, previous_context: str, window_text: str) -> dict:
    """Extract defenses from one window of text."""
    tools = [
        {
            "name": "extract_defenses_and_context",
            "description": "Extract affirmative defenses and update analysis context",
            "input_schema": {
                "type": "object",
                "properties": {
                    "updated_context": {
                        "type": "string",
                        "description": "Brief summary of what's been analyzed so far",
                    },
                    "defenses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "raw_text": {
                                    "type": "string",
                                    "description": "Exact text as it appears (e.g., 'FIRST AFFIRMATIVE DEFENSE - STATUTE OF LIMITATIONS')",  # noqa: E501
                                },
                                "name": {
                                    "type": "string",
                                    "description": "Normalized defense name (e.g., 'Statute of Limitations')",
                                },
                            },
                            "required": ["raw_text", "name"],
                        },
                    },
                },
                "required": ["updated_context", "defenses"],
            },
        }
    ]

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "extract_defenses_and_context"},
            "messages": [
                {
                    "role": "user",
                    "content": f"""You are analyzing a defendant's answer document to extract affirmative defenses.

Claim being defended: {claim_context}

Previous context: {previous_context}

Current window:
{window_text}

Extract any affirmative defenses from this window that relate to the claim. Look for:
- Numbered affirmative defenses (e.g., "FIRST AFFIRMATIVE DEFENSE", "1. Statute of Limitations")
- Sections labeled "AFFIRMATIVE DEFENSES"
- Defense arguments like: failure to state a claim, statute of limitations, laches, waiver, estoppel, contributory negligence, assumption of risk, etc.
- General denials or admissions (e.g., "Defendant denies the allegations in paragraph X")

For each defense found, provide:
- raw_text: exact heading/text as written
- name: normalized defense name

Also update the context paragraph to summarize what defenses you've seen so far.""",  # noqa: E501
                }
            ],
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
            return item["input"]

    # Fallback if no tool use found
    return {"updated_context": previous_context, "defenses": []}


def process_damages_window(claim_context: str, previous_context: str, window_text: str, claim_type: str) -> dict:
    """Extract damages from one window of text."""
    party = "plaintiff" if claim_type == "claims" else "counterclaimant/defendant"

    tools = [
        {
            "name": "extract_damages_and_context",
            "description": "Extract requested damages and update analysis context",
            "input_schema": {
                "type": "object",
                "properties": {
                    "updated_context": {
                        "type": "string",
                        "description": "Brief summary of what's been analyzed so far",
                    },
                    "damages": {
                        "type": "object",
                        "properties": {
                            "compensatory": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Compensatory/actual damages (e.g., '$50,000', 'lost profits', 'actual damages')",
                            },
                            "punitive": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Punitive/exemplary damages",
                            },
                            "statutory": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Statutory damages (e.g., 'treble damages', 'statutory damages under §XYZ')",
                            },
                            "equitable": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Equitable relief (e.g., 'injunctive relief', 'specific performance', 'declaratory judgment')",  # noqa: E501
                            },
                            "other": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Other relief (e.g., 'attorney's fees', 'costs', 'pre/post-judgment interest')",  # noqa: E501
                            },
                        },
                        "required": ["compensatory", "punitive", "statutory", "equitable", "other"],
                    },
                },
                "required": ["updated_context", "damages"],
            },
        }
    ]

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "extract_damages_and_context"},
            "messages": [
                {
                    "role": "user",
                    "content": f"""You are analyzing a legal complaint to extract damages requested by the {party}.

Claim being analyzed: {claim_context}

Previous context: {previous_context}

Current window:
{window_text}

Extract all damages and relief requested that relate to this specific claim. Look for:
- "WHEREFORE" clauses or prayer for relief sections
- Specific dollar amounts (e.g., "$50,000", "in excess of $15,000")
- Types of damages mentioned in the complaint counts
- Relief requested at the end of each count

Categorize damages as:
1. **Compensatory**: Actual/compensatory damages, economic losses, lost profits, specific dollar amounts for actual harm
2. **Punitive**: Punitive damages, exemplary damages
3. **Statutory**: Treble damages, statutory damages under specific statutes
4. **Equitable**: Injunctive relief, specific performance, declaratory judgment, rescission
5. **Other**: Attorney's fees, costs, interest, "such other relief as the court deems just"

For each damage item, provide a clear description (e.g., "$50,000 in compensatory damages", "injunctive relief", "attorney's fees").

Also update the context paragraph to summarize what damages you've seen so far.""",  # noqa: E501
                }
            ],
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
            return item["input"]

    # Fallback if no tool use found
    return {
        "updated_context": previous_context,
        "damages": {"compensatory": [], "punitive": [], "statutory": [], "equitable": [], "other": []},
    }


def deduplicate_defenses(defenses: list[dict]) -> list[dict]:
    """Deduplicate defenses using LLM to identify same defenses with different text.

    Args:
        defenses: List of {'raw_text': str, 'name': str} dicts

    Returns:
        List of {'raw_text': str, 'name': str} dicts (deduplicated)
    """
    if not defenses:
        return []

    # If only one defense, no need to deduplicate
    if len(defenses) == 1:
        return defenses

    tools = [
        {
            "name": "group_duplicate_defenses",
            "description": "Group defenses that represent the same affirmative defense",
            "input_schema": {
                "type": "object",
                "properties": {
                    "grouped_defenses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Canonical name for this defense"},
                                "raw_text": {
                                    "type": "string",
                                    "description": "Best/most complete raw text representation",
                                },
                            },
                            "required": ["name", "raw_text"],
                        },
                    }
                },
                "required": ["grouped_defenses"],
            },
        }
    ]

    # Format defenses for the prompt
    defenses_text = "\n".join([f"{i+1}. Name: {d['name']}, Raw: {d['raw_text']}" for i, d in enumerate(defenses)])

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "group_duplicate_defenses"},
            "messages": [
                {
                    "role": "user",
                    "content": f"""You have extracted affirmative defenses from an answer document using a sliding window approach. This may have created duplicates where the same defense appears multiple times with slightly different text.

Your task: Group defenses that represent the SAME affirmative defense, even if the text differs slightly.

Defenses to deduplicate:
{defenses_text}

Guidelines:
- If multiple entries are clearly the same defense (e.g., "Statute of Limitations" and "STATUTE OF LIMITATIONS"), group them
- Use the clearest/most complete raw_text as the representative
- Use the most formal name as the canonical name
- Don't merge genuinely different defenses (e.g., "Statute of Limitations" vs "Laches")

Return grouped defenses with:
- name: canonical/best name for the defense
- raw_text: the most complete/clear raw text variant""",  # noqa: E501
                }
            ],
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
            return item["input"]["grouped_defenses"]

    # Fallback: no deduplication
    return defenses


def extract_raw_defenses_for_claim(claim_context: str, answer_chunks: list[str], window_size: int = 3) -> list[dict]:
    """Extract defenses for a specific claim using sliding window.

    Args:
        claim_context: Description of the claim being defended against
        answer_chunks: List of text chunks from answer document
        window_size: Number of chunks to process at once

    Returns:
        List of {'raw_text': str, 'name': str} dicts
    """
    all_defenses = []
    current_context = f"Beginning analysis of answer for defenses to: {claim_context}"

    # Slide through chunks with overlap
    for i in range(0, len(answer_chunks), window_size - 1):
        window_chunks = answer_chunks[i : i + window_size]
        window_text = "\n".join(window_chunks)

        # Process this window
        result = process_defense_window(
            claim_context=claim_context, previous_context=current_context, window_text=window_text
        )

        # Update context for next iteration
        current_context = result["updated_context"]

        # Collect defenses found in this window
        all_defenses.extend(result["defenses"])

    # Deduplicate defenses for this claim
    if all_defenses:
        deduplicated = deduplicate_defenses(all_defenses)
        return deduplicated

    return []


def extract_damages_for_claim(
    claim_context: str, complaint_chunks: list[str], window_size: int = 3, claim_type: str = "claims"
) -> dict:
    """Extract damages for a specific claim using sliding window.

    Args:
        claim_context: Description of the claim
        complaint_chunks: List of text chunks from complaint document
        window_size: Number of chunks to process at once
        claim_type: Either "claims" or "counterclaims"

    Returns:
        Dict with categorized damages
    """
    all_damages = {"compensatory": [], "punitive": [], "statutory": [], "equitable": [], "other": []}

    party = "plaintiff" if claim_type == "claims" else "counterclaimant/defendant"
    current_context = f"Beginnin analysis of {claim_type} for damages requested by {party} for: {claim_context}"

    # Slide through chunks with overlap
    for i in range(0, len(complaint_chunks), window_size - 1):
        window_chunks = complaint_chunks[i : i + window_size]
        window_text = "\n".join(window_chunks)

        # Process this window
        result = process_damages_window(
            claim_context=claim_context,
            previous_context=current_context,
            window_text=window_text,
            claim_type=claim_type,
        )

        # Update context for next iteration
        current_context = result["updated_context"]

        # Collect damages found in this window
        for category, all_damages_category in all_damages.items():
            all_damages_category.extend(result["damages"].get(category, []))

    # Deduplicate damages in each category
    for category, all_damages_category in all_damages.items():
        if all_damages_category:
            all_damages[category] = list(set(all_damages_category))  # Simple dedup

    return all_damages

import logging

import instruction_processing

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _unique_by_number(instructions: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for inst in instructions or []:
        num = (inst or {}).get("number")
        if num and num not in seen:
            seen.add(num)
            out.append(inst)
        elif not num:
            # Keep items without numbers (e.g., some custom outputs)
            out.append(inst)
    return out


def lambda_handler(event, _context):
    """
    Generate instructions for a single item (claim or counterclaim).

    Input:
      {
        "type": "claim" | "counterclaim",
        "item": { "claim_id": str, "defenses": [...], "damages": {...} },
        "case_facts": str,
        "config": { ... }
      }

    Output:
      {
        "instructions": [ ... ],
        "processed_item": { "type": str, "claim_id": str, "category": str }
      }
    """
    try:
        item_type = event.get("type")
        item = event.get("item") or {}
        case_facts = event.get("case_facts") or ""
        claim_id = item.get("claim_id")
        if item_type not in ("claim", "counterclaim"):
            raise ValueError("'type' must be 'claim' or 'counterclaim'")
        if not claim_id:
            raise ValueError("item.claim_id is required")
    except Exception as e:
        logger.error(f"Invalid input: {e}")
        raise

    claim = instruction_processing.database_get_claim_by_id(claim_id)
    if not claim:
        logger.warning(f"Claim not found in database: {claim_id}")
        return {"instructions": [], "processed_item": {"type": item_type, "claim_id": claim_id, "category": None}}

    # Preload available standard categories from DynamoDB once per invoke
    all_sji = instruction_processing._scan_all(instruction_processing._sji_table)
    standard_instruction_categories = sorted(
        {
            (r.get("category_number"), r.get("category_title"))
            for r in all_sji
            if r.get("category_number") and r.get("category_title")
        }
    )

    category = instruction_processing.match_claim_to_category(
        claim_title=claim.get("title"),
        case_facts=case_facts,
        standard_categories=standard_instruction_categories,
    )

    out_instructions: list[dict] = []

    # 4xx or custom per item
    if category != "CUSTOM":
        sel = instruction_processing.select_and_customize_instructions(
            category_number=category,
            claim=claim,
            claim_elements=claim.get("elements"),
            defenses=(item.get("defenses", []) if item_type == "claim" else []),
            case_facts=case_facts,
            damages=item.get("damages", {}),
        )
        out_instructions.extend(sel)
    else:
        cust = instruction_processing.generate_custom_instructions(
            claim_info=item, claim=claim, case_facts=case_facts
        )
        if cust:
            out_instructions.append(cust)

    # 5xx damages per item
    try:
        chapters = instruction_processing.llm_choose_damages_chapters(
            claim_title=(claim or {}).get("title"),
            claim_elements=claim.get("elements"),
            defenses=(item.get("defenses", []) if item_type == "claim" else []),
            case_facts=case_facts,
            damages=item.get("damages", {}),
        )
        for cat in chapters:
            sel = instruction_processing.select_and_customize_instructions(
                category_number=cat,
                claim=claim,
                claim_elements=claim.get("elements"),
                defenses=(item.get("defenses", []) if item_type == "claim" else []),
                case_facts=case_facts,
                damages=item.get("damages", {}),
            )
            out_instructions.extend(sel)
    except Exception:
        # Don't fail the item for damages stage
        pass

    out_instructions = _unique_by_number(out_instructions)

    return {
        "instructions": out_instructions,
        "processed_item": {"type": item_type, "claim_id": claim_id, "category": category},
    }

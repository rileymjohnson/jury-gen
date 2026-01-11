import logging
import os
import sys

# Allow importing shared helpers from generate_instructions package folder
CURRENT_DIR = os.path.dirname(__file__)
PARENT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", "generate_instructions"))
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

import instruction_processing  # noqa: E402


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
            out.append(inst)
    return out


def lambda_handler(event, _context):
    """
    Aggregate per-item instruction results and add 100s/200s and 600s series.

    Input:
      {
        "claim_results": [ {"instructions":[...], "processed_item": {...}}, ... ],
        "counterclaim_results": [ ... ],
        "case_facts": str,
        "witnesses": [ {first_name,last_name} ],
        "config": {...},
        "claims": [ ... ],
        "counterclaims": [ ... ]
      }

    Output:
      [ { number, customized_text, ... }, ... ]
    """
    claim_results = event.get("claim_results") or []
    counterclaim_results = event.get("counterclaim_results") or []
    case_facts = event.get("case_facts") or ""
    witnesses = event.get("witnesses") or []
    config = event.get("config") or {}
    claims = event.get("claims") or []
    counterclaims = event.get("counterclaims") or []

    all_instructions: list[dict] = []

    # 201.1 (+ optional 101.1) and then 201.2, 201.3
    try:
        parts_201_1 = instruction_processing._generate_201_1(
            config=config, case_facts=case_facts, witnesses=witnesses
        )
        if parts_201_1:
            include_oath = bool(config.get("include_so_help_you_god", False))
            pre = [x for x in parts_201_1 if not (x.get("meta") or {}).get("is_continuation_part")]
            post = [x for x in parts_201_1 if (x.get("meta") or {}).get("is_continuation_part")]
            if include_oath:
                all_instructions.extend(pre)
                oath = instruction_processing._generate_101_1(config=config)
                if oath:
                    all_instructions.append(oath)
                all_instructions.extend(post)
            else:
                all_instructions.extend(parts_201_1)
    except Exception:
        pass

    try:
        si_201_2 = instruction_processing._generate_201_2(config=config)
        if si_201_2:
            all_instructions.append(si_201_2)
    except Exception:
        pass

    try:
        si_201_3 = instruction_processing._generate_201_3()
        if si_201_3:
            all_instructions.append(si_201_3)
    except Exception:
        pass

    # Flatten per-item outputs
    item_instructions = []
    for r in claim_results:
        item_instructions.extend((r or {}).get("instructions") or [])
    for r in counterclaim_results:
        item_instructions.extend((r or {}).get("instructions") or [])

    # Split non-5xx and 5xx to preserve ordering similar to original pipeline
    non_5xx = []
    only_5xx = []
    for inst in item_instructions:
        num = str((inst or {}).get("number") or "")
        prefix = num.split(".")[0] if "." in num else num
        if prefix in {"501", "502", "503", "504"}:
            only_5xx.append(inst)
        else:
            non_5xx.append(inst)

    non_5xx = _unique_by_number(non_5xx)
    only_5xx = _unique_by_number(only_5xx)

    all_instructions.extend(non_5xx)
    all_instructions.extend(only_5xx)

    # 600 series
    try:
        s601_1 = instruction_processing._generate_601_1()
        if s601_1:
            all_instructions.append(s601_1)
    except Exception:
        pass

    try:
        s601_2 = instruction_processing._generate_601_2(config=config)
        if s601_2:
            all_instructions.append(s601_2)
    except Exception:
        pass

    try:
        s601_3 = instruction_processing._generate_601_3(config=config)
        if s601_3:
            all_instructions.append(s601_3)
    except Exception:
        pass

    try:
        s601_4 = instruction_processing._generate_601_4(claims=claims, counterclaims=counterclaims)
        if s601_4:
            all_instructions.append(s601_4)
    except Exception:
        pass

    try:
        s601_5 = instruction_processing._generate_601_5(config=config)
        if s601_5:
            all_instructions.append(s601_5)
    except Exception:
        pass

    return all_instructions

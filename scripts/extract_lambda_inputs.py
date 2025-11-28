import argparse
import json
from pathlib import Path
import re

# Map short names to the function-name fragment used in ARNs
LAMBDA_NAME_FRAGMENTS: dict[str, str] = {
    "extract_legal_claims": "ExtractLegalClaims",
    "extract_witnesses": "ExtractWitnesses",
    "extract_case_facts": "ExtractCaseFacts",
    "enrich_legal_item": "EnrichLegalItem",
    "generate_instructions": "GenerateInstructions",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--history", required=True, help="Path to Step Functions history JSON file")
    p.add_argument(
        "--lambdas",
        nargs="+",
        choices=sorted(LAMBDA_NAME_FRAGMENTS.keys()),
        required=True,
        help="Target lambda short names to extract inputs for",
    )
    p.add_argument("--outdir", default=None, help="Optional directory to write per-invocation inputs as JSON files")
    p.add_argument("--write-files", action="store_true", help="When set, write inputs to files under outdir")
    p.add_argument("--max-print", type=int, default=3, help="Max examples to print per lambda (defaults to 3)")
    return p.parse_args()


def load_history(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("History JSON must be a list of events")
    return data


def match_lambda(resource_arn: str, name_fragment: str) -> bool:
    # Match function name fragment within the ARN (case-sensitive as AWS is case-sensitive here)
    # e.g., arn:aws:lambda:...:function:JuryApp-ExtractLegalClaims-dev
    return bool(re.search(rf":function:[^:]*{re.escape(name_fragment)}[^:]*$", resource_arn))


def main() -> None:  # noqa: PLR0912
    args = parse_args()
    history_path = Path(args.history)
    outdir = Path(args.outdir) if args.outdir else None

    events = load_history(history_path)

    # Collect inputs per lambda short name
    collected: dict[str, list[dict]] = {name: [] for name in args.lambdas}

    for ev in events:
        if ev.get("type") != "LambdaFunctionScheduled":
            continue
        details = ev.get("lambdaFunctionScheduledEventDetails") or {}
        resource = details.get("resource") or ""
        raw_input = details.get("input")
        if raw_input is None:
            continue

        # Determine which target lambda (if any) this event is for
        for short_name in args.lambdas:
            frag = LAMBDA_NAME_FRAGMENTS[short_name]
            if match_lambda(resource, frag):
                try:
                    payload = json.loads(raw_input)
                except json.JSONDecodeError:
                    # Some histories may already include JSON objects; accept raw
                    payload = raw_input
                collected[short_name].append(payload)

    # Optionally write files
    if args.write_files:
        if not outdir:
            raise SystemExit("--write-files requires --outdir")
        outdir.mkdir(parents=True, exist_ok=True)
        for short_name, items in collected.items():
            for idx, payload in enumerate(items, start=1):
                out_path = outdir / f"{short_name}-{idx:03d}.json"
                with out_path.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)

    # Print summary and sample payloads
    for short_name in args.lambdas:
        items = collected.get(short_name, [])
        print(f"\n=== {short_name} === ({len(items)} invocation(s) found)")
        for payload in items[: max(0, args.max_print)]:
            print(json.dumps(payload, indent=2, ensure_ascii=False))

    # Exit code indicates whether anything was found
    total = sum(len(v) for v in collected.values())
    if total == 0:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

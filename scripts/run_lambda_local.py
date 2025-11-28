import argparse
from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import sys

import extract_lambda_inputs as extractor

LAMBDA_DIR_MAP = {
    "enrich_legal_item": "enrich_legal_item",
    "extract_case_facts": "extract_case_facts",
    "extract_legal_claims": "extract_legal_claims",
    "extract_witnesses": "extract_witnesses",
    "generate_instructions": "generate_instructions",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run selected Lambda locally using inputs extracted from Step Functions history."
    )
    p.add_argument(
        "--lambda",
        dest="lambda_name",
        choices=sorted(LAMBDA_DIR_MAP.keys()),
        required=True,
        help="Target lambda to invoke",
    )
    p.add_argument(
        "--example",
        choices=["one", "two"],
        required=True,
        help="Which example folder to use (examples/<example>)",
    )
    p.add_argument(
        "--index",
        type=int,
        default=None,
        help="Optional 1-based index to run a single input (e.g., 1 runs *-001.json).",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Run across all inputs for this lambda (default for enrich_legal_item).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit how many inputs to run (from start).",
    )
    p.add_argument(
        "--save-outdir",
        default=None,
        help="If set, write outputs as JSON to this directory.",
    )
    p.add_argument(
        "--region",
        default=None,
        help="AWS region to set for boto3 clients (sets AWS_REGION and AWS_DEFAULT_REGION).",
    )
    p.add_argument(
        "--environment",
        default="dev",
        help="Environment name used for table suffixes (e.g., dev → Claims-dev).",
    )
    p.add_argument(
        "--ensure-inputs",
        action="store_true",
        help=(
            "If inputs are missing, auto-extract them from examples/<example>/sfn_events.json "
            "using scripts/extract_lambda_inputs.py."
        ),
    )
    return p.parse_args()


def ensure_inputs(lambda_name: str, example: str) -> Path:
    inputs_dir = Path("examples") / example / "inputs"
    if inputs_dir.exists() and any(inputs_dir.glob(f"{lambda_name}-*.json")):
        return inputs_dir

    # Try to generate by calling the extractor if requested outside
    raise FileNotFoundError(
        f"No inputs found for {lambda_name} in {inputs_dir}. Run extract_lambda_inputs.py first."
    )


def maybe_auto_extract(lambda_names: list[str], example: str) -> None:
    history = Path("examples") / example / "sfn_events.json"
    outdir = Path("examples") / example / "inputs"
    if not history.exists():
        return
    # Use the same Python interpreter
    # Invoke the extractor as a module to avoid subprocess on Windows/WSL issues
    sys.path.insert(0, str(Path("scripts").resolve()))
    try:
        class Args:
            history = str(history)
            lambdas = lambda_names
            outdir = str(outdir)
            write_files = True
            max_print = 0

        # Emulate extractor main bits
        events = extractor.load_history(Path(Args.history))
        collected = {name: [] for name in Args.lambdas}
        for ev in events:
            if ev.get("type") != "LambdaFunctionScheduled":
                continue
            details = ev.get("lambdaFunctionScheduledEventDetails") or {}
            resource = details.get("resource") or ""
            raw_input = details.get("input")
            if raw_input is None:
                continue
            for short_name in Args.lambdas:
                frag = extractor.LAMBDA_NAME_FRAGMENTS[short_name]
                if extractor.match_lambda(resource, frag):
                    try:
                        payload = json.loads(raw_input)
                    except json.JSONDecodeError:
                        payload = raw_input
                    collected[short_name].append(payload)
        outdir.mkdir(parents=True, exist_ok=True)
        for short_name, items in collected.items():
            for idx, payload in enumerate(items, start=1):
                out_path = outdir / f"{short_name}-{idx:03d}.json"
                with out_path.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
    finally:
        # Clean path change
        if str(Path("scripts").resolve()) in sys.path:
            sys.path.remove(str(Path("scripts").resolve()))


def resolve_handler(lambda_name: str) -> tuple[Callable, Path]:
    lambda_subdir = LAMBDA_DIR_MAP[lambda_name]
    lambda_dir = Path("lambdas") / lambda_subdir
    if not lambda_dir.exists():
        raise FileNotFoundError(f"Lambda directory not found: {lambda_dir}")

    # Ensure local imports resolve
    lambda_path = str(lambda_dir.resolve())
    if lambda_path not in sys.path:
        sys.path.insert(0, lambda_path)

    # Dev hot-reload: purge previously loaded modules from this lambda folder
    try:
        lambda_root = lambda_dir.resolve()
        to_delete = []
        for name, mod in list(sys.modules.items()):
            f = getattr(mod, "__file__", None)
            if not f:
                continue
            try:
                p = Path(f).resolve()
                if str(p).startswith(str(lambda_root)):
                    to_delete.append(name)
            except Exception:
                continue
        for name in to_delete:
            sys.modules.pop(name, None)
    except Exception:
        pass

    # Load the exact main.py for this lambda under a unique module name to avoid cache collisions
    module_name = f"lambda_{lambda_name}_main"
    try:
        main_py = lambda_dir / "main.py"
        spec = spec_from_file_location(module_name, main_py)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {main_py}")
        module = module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", str(e))
        raise SystemExit(
            "Failed to import Lambda module dependencies. Missing module: "
            f"{missing}. Install required deps (e.g., 'pip install boto3') or activate your venv."
        ) from e

    if not hasattr(module, "lambda_handler"):
        raise AttributeError(f"main.py in {lambda_dir} does not expose lambda_handler")
    return module.lambda_handler, lambda_dir


def collect_input_files(lambda_name: str, example: str, ensure: bool, default_all: bool) -> list[Path]:
    inputs_dir = Path("examples") / example / "inputs"
    if ensure and not (inputs_dir.exists() and any(inputs_dir.glob(f"{lambda_name}-*.json"))):
        # Try auto-extract
        maybe_auto_extract([lambda_name], example)

    # Now collect
    files = sorted(inputs_dir.glob(f"{lambda_name}-*.json"))
    if default_all and not files:
        raise FileNotFoundError(f"No input files found for {lambda_name} under {inputs_dir}")
    return files


def main() -> None:  # noqa: PLR0912, PLR0915
    args = parse_args()

    default_all = args.lambda_name == "enrich_legal_item"
    files = collect_input_files(args.lambda_name, args.example, args.ensure_inputs, default_all)

    # Ensure AWS region is set before importing modules that create clients at import time
    def set_region_env(region_val: str) -> None:
        if region_val:
            os.environ.setdefault("AWS_REGION", region_val)
            os.environ.setdefault("AWS_DEFAULT_REGION", region_val)

    if args.region:
        set_region_env(args.region)
    elif not (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")):
        # Try to infer from the example's history ARN
        history = Path("examples") / args.example / "sfn_events.json"
        try:
            data = json.loads(history.read_text(encoding="utf-8"))
            region = None
            for ev in data:
                if ev.get("type") == "LambdaFunctionScheduled":
                    arn = (ev.get("lambdaFunctionScheduledEventDetails") or {}).get("resource") or ""
                    parts = arn.split(":")  # arn:aws:lambda:<region>:
                    if len(parts) > 3 and parts[2] == "lambda":  # noqa: PLR2004
                        region = parts[3]
                        break
            if region:
                set_region_env(region)
        except Exception:
            pass

    # Ensure expected DynamoDB env vars when not provided
    env_name = args.environment or "dev"
    def set_if_missing(key: str, val: str) -> None:
        if not os.environ.get(key):
            os.environ[key] = val

    if args.lambda_name == "extract_legal_claims":
        set_if_missing("DYNAMODB_CLAIMS_TABLE_NAME", f"Claims-{env_name}")
    if args.lambda_name == "generate_instructions":
        set_if_missing("DYNAMODB_CLAIMS_TABLE_NAME", f"Claims-{env_name}")
        set_if_missing("DYNAMODB_STANDARD_JURY_INSTRUCTIONS_TABLE_NAME", f"StandardJuryInstructions-{env_name}")

    # Narrow to a single file if requested
    if args.index is not None:
        if args.index < 1 or args.index > len(files):
            raise SystemExit(f"--index out of range (1..{len(files)})")
        files = [files[args.index - 1]]
    elif args.all or default_all:
        if args.limit is not None:
            files = files[: args.limit]
    else:
        # default: first one
        files = files[:1]

    handler, lambda_dir = resolve_handler(args.lambda_name)

    save_dir = Path(args.save_outdir) if args.save_outdir else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    for i, file in enumerate(files, start=1):
        with file.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        print(f"\n=== RUN {args.lambda_name} :: {file} ===")
        result = handler(payload, None)
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if save_dir:
            out_path = save_dir / f"{args.lambda_name}-out-{i:03d}.json"
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()

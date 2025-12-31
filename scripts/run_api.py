import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import requests

DEFAULT_API_URL = "https://z8rj47cgo7.execute-api.us-east-1.amazonaws.com/dev"
DEFAULT_API_KEY = "izVg8ltdAPfuvGVmnKZ5vLAswOAP4Nrz"


def read_json(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def call_api_sign(base_url: str, api_key: str) -> dict[str, Any]:
    url = f"{base_url}/sign"
    r = requests.post(url, headers={"x-api-key": api_key})
    r.raise_for_status()
    return r.json()


def upload_file(put_url: str, path: Path, content_type: str = "application/pdf") -> None:
    with path.open("rb") as f:
        r = requests.put(put_url, data=f, headers={"Content-Type": content_type})
    r.raise_for_status()


def _build_default_config() -> dict[str, Any]:
    # Provide sensible defaults for required config fields
    return {
        "incident_date": "2024-01-15",
        "incident_location": "Miami, Florida",
        "additional_voir_dire_info": "None.",
        "include_so_help_you_god": True,
        "judge_name": "Judge Smith",
        "plaintiff_name": "John Doe",
        "defendant_name": "Rachel Rowe",
        "plaintiff_attorney_name": "Alex Parker",
        "plaintiff_attorney_gender": "male",
        "defendant_attorney_name": "Morgan Lee",
        "defendant_attorney_gender": "female",
        "court_clerk_name": "Taylor Brooks",
        "court_clerk_gender": "neutral",
        "court_reporter_name": "Jordan Cruz",
        "court_reporter_gender": "neutral",
        "bailiff_name": "Casey Quinn",
        "bailiff_gender": "neutral",
        "electronic_device_policy": "A",
        "permitted_ex_parte_communications": [
            "juror parking",
            "location of break areas",
            "how and when to assemble for duty",
            "dress",
            "what personal items can be brought into the courthouse or jury room",
        ],
        "has_foreign_language_witnesses": False,
        # Optional toggles for future use
        "plaintiff_is_pro_se": False,
        "defendant_is_pro_se": False,
        "has_uim_carrier": False,
    }


def call_api_start(  # noqa: PLR0913
    base_url: str,
    api_key: str,
    complaint_key: str,
    answer_key: str,
    witness_key: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    url = f"{base_url}/jury/start"
    body = {
        "complaint_key": complaint_key,
        "answer_key": answer_key,
        "witness_key": witness_key,
        "config": config,
    }
    r = requests.post(url, json=body, headers={"x-api-key": api_key, "Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def call_api_status(base_url: str, api_key: str, job_id: str) -> dict[str, Any]:
    url = f"{base_url}/jury/status/{job_id}"
    r = requests.get(url, headers={"x-api-key": api_key})
    if r.status_code == 404:  # noqa: PLR2004
        return {"_not_found": True}
    r.raise_for_status()
    return r.json()


def _infer_region_from_url(api_url: str) -> str:
    try:
        host = api_url.split("//", 1)[1].split("/", 1)[0]
        parts = host.split(".")
        if len(parts) >= 5 and parts[1] == "execute-api":  # noqa: PLR2004
            return parts[2]
    except Exception:
        pass
    return "us-east-1"


def _capture_sfn_history_cli(execution_arn: str, region: str, out_path: Path, aws_profile: str | None = None) -> None:
    if shutil.which("aws") is None:
        print("AWS CLI not found; skipping Step Functions history capture.")
        return
    events: list[dict] = []
    next_token: str | None = None
    while True:
        cmd = [
            "aws",
            "stepfunctions",
            "get-execution-history",
            "--execution-arn",
            execution_arn,
            "--region",
            region,
            "--max-results",
            "1000",
        ]
        if next_token:
            cmd += ["--next-token", next_token]
        env = None
        if aws_profile:
            env = dict(**{k: v for k, v in (dict(**os.environ)).items() if True})
            env["AWS_PROFILE"] = aws_profile
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if res.returncode != 0:
            try:
                enc = sys.stdout.encoding or "utf-8"
                safe_err = (res.stderr or "").encode(enc, errors="replace").decode(enc, errors="replace")
                print("Failed to fetch execution history:", safe_err.strip())
            except Exception:
                print("Failed to fetch execution history (stderr encoding issue)")
            break
        try:
            payload = json.loads(res.stdout)
        except Exception as e:
            print("Failed to parse execution history JSON:", e)
            break
        events.extend(payload.get("events", []))
        nt = payload.get("nextToken") or payload.get("next_token")
        if not nt:
            break
        next_token = nt

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({"events": events, "executionArn": execution_arn, "region": region}, f, indent=2)
    print(f"Saved Step Functions history to {out_path}")


def run(  # noqa: PLR0913, PLR0915
    example: str,
    env: str,
    out_root: Path,
    base_url: str,
    api_key: str,
    capture_history: bool = True,
    region: str | None = None,
    aws_profile: str | None = None,
) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    base_url = base_url.rstrip("/")

    ex_dir = repo_root / "examples" / example
    files_def = read_json(ex_dir / "files.json")
    complaint = ex_dir / files_def["complaint"]
    answer = ex_dir / files_def["answer"]
    witness = ex_dir / files_def["witness_list"]

    run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / f"{env}-{example}-{run_id}"
    (out_dir / "input").mkdir(parents=True, exist_ok=True)
    (out_dir / "responses").mkdir(parents=True, exist_ok=True)

    # 1) Get presigned URLs
    signer_resp = call_api_sign(base_url, api_key)
    write_json(out_dir / "responses" / "sign.json", signer_resp)

    uploads = signer_resp.get("uploads", {})
    c_info = uploads.get("complaint")
    a_info = uploads.get("answer")
    w_info = uploads.get("witness")
    if not (c_info and a_info and w_info):
        raise SystemExit("api_signer did not return expected upload slots")

    # 2) Upload files
    upload_file(c_info["presigned_url"], complaint, c_info.get("content_type", "application/pdf"))
    upload_file(a_info["presigned_url"], answer, a_info.get("content_type", "application/pdf"))
    upload_file(w_info["presigned_url"], witness, w_info.get("content_type", "application/pdf"))

    # 3) Start the workflow
    config = _build_default_config()
    start_resp = call_api_start(base_url, api_key, c_info["key"], a_info["key"], w_info["key"], config)
    write_json(out_dir / "responses" / "start.json", start_resp)

    job_id = start_resp.get("jury_instruction_id")
    if not job_id:
        raise SystemExit("api_start did not return jury_instruction_id")
    execution_arn = start_resp.get("executionArn")

    # 4) Poll status
    poll_path = out_dir / "responses" / "status_progress.jsonl"
    deadline = time.time() + 60 * 30  # 30 minutes
    last_status = None
    with poll_path.open("w", encoding="utf-8") as f:
        while time.time() < deadline:
            status = call_api_status(base_url, api_key, job_id)
            f.write(json.dumps(status) + "\n")
            f.flush()

            if status.get("_not_found"):
                time.sleep(3)
                continue

            last_status = status
            s = str(status.get("status") or "").upper()
            if s == "COMPLETE":
                break
            time.sleep(10)

    if not last_status or str(last_status.get("status", "")).upper() != "COMPLETE":
        raise SystemExit("Timed out waiting for job completion. See status_progress.jsonl for details.")

    # 5) Write outputs
    final = {
        "job_id": job_id,
        "status": last_status.get("status"),
        "case_facts": last_status.get("case_facts"),
        "witnesses": last_status.get("witnesses"),
        "claims": last_status.get("claims"),
        "counterclaims": last_status.get("counterclaims"),
        "instructions": last_status.get("jury_instructions_text"),
        "source_files": last_status.get("source_files"),
        "createdAt": last_status.get("createdAt"),
        "completedAt": last_status.get("completedAt"),
    }
    write_json(out_dir / "final.json", final)

    # 6) Optionally capture Step Functions execution history
    if capture_history and execution_arn:
        effective_region = region or _infer_region_from_url(base_url)
        _capture_sfn_history_cli(
            execution_arn,
            effective_region,
            out_dir / "responses" / "sfn_history.json",
            aws_profile=aws_profile,
        )

    return out_dir


def main():
    ap = argparse.ArgumentParser(description="Run remote jury-gen pipeline via API Gateway")
    ap.add_argument("--example", choices=["one", "two"], help="Which example folder to use")
    ap.add_argument("--env", choices=["dev", "prod"], default="dev", help="Tag outputs with env (no functional change)")
    ap.add_argument("--out", default="runs", help="Output folder root (default: runs)")
    ap.add_argument("--api-url", default=DEFAULT_API_URL, help="Base API URL (default: dev URL)")
    ap.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key (default: dev key)")
    ap.add_argument("--no-capture-history", action="store_true", help="Do not capture Step Functions execution history")
    ap.add_argument("--region", default=None, help="AWS region for Step Functions history (defaults from API URL)")
    ap.add_argument("--aws-profile", default=None, help="AWS profile to use for history capture (optional)")
    args = ap.parse_args()

    out_dir = run(
        args.example,
        args.env,
        Path(args.out),
        args.api_url,
        args.api_key,
        capture_history=not args.no_capture_history,
        region=args.region,
        aws_profile=args.aws_profile,
    )
    print(f"Done. Results in: {out_dir}")


if __name__ == "__main__":
    main()

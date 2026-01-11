import argparse
import base64
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
from tqdm import tqdm

DEFAULT_API_URL = "https://2c4krnu3gj.execute-api.us-east-1.amazonaws.com/dev"
DEFAULT_API_KEY = "RbqaKXztZPYB1fl6gA1Im1zfUQnTPBTG"


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


class _ProgressFile:
    def __init__(self, fp, progress=None):
        self._fp = fp
        self._progress = progress

    def __getattr__(self, name):
        # Delegate unknown attributes (e.g., 'mode', 'name', etc.) to the underlying file
        return getattr(self._fp, name)

    def read(self, n=-1):
        data = self._fp.read(n)
        if self._progress and data:
            self._progress.update(len(data))
        return data

    def fileno(self):
        return self._fp.fileno()

    def seek(self, *args, **kwargs):
        return self._fp.seek(*args, **kwargs)

    def tell(self):
        return self._fp.tell()

    def close(self):
        return self._fp.close()


def upload_file(put_url: str, path: Path, content_type: str = "application/pdf") -> None:
    total = path.stat().st_size if path.exists() else None
    bar = None
    if tqdm and total:
        bar = tqdm(total=total, unit="B", unit_scale=True, desc=f"Upload {path.name}")
    try:
        with path.open("rb") as base:
            fp = _ProgressFile(base, progress=bar)
            r = requests.put(put_url, data=fp, headers={"Content-Type": content_type})
        r.raise_for_status()
    finally:
        if bar:
            bar.close()


def _build_default_config() -> dict[str, Any]:
    # Provide sensible defaults for required config fields
    return {
        "incident_date": "2024-01-15",
        "incident_location": "Miami, Florida",
        "additional_voir_dire_info": "None.",
        "include_so_help_you_god": True,
        "oath_administered_by": "clerk",  # "judge" or "clerk"
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
        "has_expert_witnesses": False,
        # Optional toggles for future use
        "plaintiff_is_pro_se": False,
        "defendant_is_pro_se": False,
        "has_uim_carrier": False,
        # When to give final instructions relative to final argument
        # Allowed: "before_final_argument" | "after_final_argument"
        "final_instructions_timing": "before_final_argument",
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


def _poll_status_with_progress(  # noqa: PLR0913
    base_url: str,
    api_key: str,
    job_id: str,
    *,
    out_path: Path,
    max_wait_sec: int = 60 * 30,
    interval_sec: int = 10,
) -> dict[str, Any]:
    """Poll the job status with a progress bar until COMPLETE or timeout.

    Writes a JSONL of status snapshots to out_path. Returns the final status dict.
    """
    deadline = time.time() + max_wait_sec
    last_status: dict[str, Any] | None = None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = max_wait_sec
    bar = tqdm(total=total, unit="s", desc="Polling status", leave=True) if tqdm else None
    try:
        with out_path.open("w", encoding="utf-8") as f:
            while time.time() < deadline:
                status = call_api_status(base_url, api_key, job_id)
                f.write(json.dumps(status) + "\n")
                f.flush()

                if status.get("_not_found"):
                    time.sleep(3)
                else:
                    last_status = status
                    s = str(status.get("status") or "").upper()
                    # Try to show instruction count if available
                    count = 0
                    try:
                        ji = status.get("jury_instructions_text") or []
                        if isinstance(ji, list):
                            count = len(ji)
                    except Exception:
                        count = 0
                    if bar:
                        elapsed = int(total - max(0, int(deadline - time.time())))
                        bar.n = min(elapsed, total)
                        bar.set_description(f"Status: {s or 'PENDING'} | Instructions: {count}")
                        bar.refresh()
                    if s == "COMPLETE":
                        break
                    time.sleep(interval_sec)
            return last_status or {}
    finally:
        if bar:
            bar.close()


def call_api_export_docx(base_url: str, api_key: str, job_id: str) -> bytes:
    """Download the generated DOCX for a completed job.

    Returns raw bytes of the .docx file. Raises for non-200 status codes.
    """
    url = f"{base_url}/jury/export/{job_id}"
    r = requests.get(url, headers={"x-api-key": api_key}, stream=True)
    # Allow 404/409 to raise with context
    if r.status_code != 200:  # noqa: PLR2004
        try:
            payload = r.json()
        except Exception:
            payload = {"error": f"HTTP {r.status_code}", "body": r.text[:500]}
        raise RuntimeError(f"Export failed: {payload}")

    content = r.content
    # If API Gateway didn't apply binary decoding, we may receive base64 text.
    # A valid .docx begins with bytes 'PK\x03\x04'. Base64-encoded DOCX often starts with 'UEsDB'.
    if not content.startswith(b"PK"):
        try:
            decoded = base64.b64decode(content, validate=True)
            if decoded.startswith(b"PK"):
                return decoded
        except Exception:
            pass
    return content


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


def run(  # noqa: PLR0912, PLR0913, PLR0915
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
    # Record which local input files were used
    write_json(
        out_dir / "input" / "files_used.json",
        {
            "complaint": str(complaint),
            "answer": str(answer),
            "witness_list": str(witness),
        },
    )

    # 1) Get presigned URLs
    signer_resp = call_api_sign(base_url, api_key)
    write_json(out_dir / "responses" / "sign.json", signer_resp)

    uploads = signer_resp.get("uploads", {})
    c_info = uploads.get("complaint")
    a_info = uploads.get("answer")
    w_info = uploads.get("witness")
    if not (c_info and a_info and w_info):
        raise SystemExit("api_signer did not return expected upload slots")

    # 2) Copy inputs locally and upload files
    #    Keep a local snapshot of the exact inputs used
    try:
        shutil.copy2(complaint, out_dir / "input" / complaint.name)
        shutil.copy2(answer, out_dir / "input" / answer.name)
        shutil.copy2(witness, out_dir / "input" / witness.name)
    except Exception:
        pass

    # Upload to presigned URLs
    upload_file(c_info["presigned_url"], complaint, c_info.get("content_type", "application/pdf"))
    upload_file(a_info["presigned_url"], answer, a_info.get("content_type", "application/pdf"))
    upload_file(w_info["presigned_url"], witness, w_info.get("content_type", "application/pdf"))

    # 3) Start the workflow
    config = _build_default_config()
    # Save request we send to /jury/start and persist config under input/
    start_request = {
        "complaint_key": c_info["key"],
        "answer_key": a_info["key"],
        "witness_key": w_info["key"],
        "config": config,
    }
    write_json(out_dir / "responses" / "start_request.json", start_request)
    write_json(out_dir / "input" / "config.json", config)

    start_resp = call_api_start(base_url, api_key, c_info["key"], a_info["key"], w_info["key"], config)
    write_json(out_dir / "responses" / "start.json", start_resp)

    job_id = start_resp.get("jury_instruction_id")
    if not job_id:
        raise SystemExit("api_start did not return jury_instruction_id")
    execution_arn = start_resp.get("executionArn")

    # 4) Poll status
    poll_path = out_dir / "responses" / "status_progress.jsonl"
    last_status = _poll_status_with_progress(
        base_url,
        api_key,
        job_id,
        out_path=poll_path,
        max_wait_sec=60 * 30,
        interval_sec=10,
    )

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
    # Also capture the raw final DynamoDB item for completeness
    write_json(out_dir / "responses" / "final_status.json", last_status)

    # 6) Export DOCX and save alongside outputs
    try:
        docx_path = out_dir / f"JuryInstructions-{job_id}.docx"
        # Stream download with progress when possible
        url = f"{base_url}/jury/export/{job_id}"
        r = requests.get(url, headers={"x-api-key": api_key}, stream=True)
        if r.status_code != 200:  # noqa: PLR2004
            try:
                payload = r.json()
            except Exception:
                payload = {"error": f"HTTP {r.status_code}", "body": r.text[:500]}
            raise RuntimeError(f"Export failed: {payload}")

        total = None
        try:
            total = int(r.headers.get("Content-Length")) if r.headers.get("Content-Length") else None
        except Exception:
            total = None

        # Peek first chunk
        first = next(r.iter_content(chunk_size=8192), b"")
        if first and not first.startswith(b"PK"):
            # Might be base64 body
            rest = b"".join([first, *list(r.iter_content(chunk_size=262144))])
            try:
                data = base64.b64decode(rest, validate=True)
            except Exception:
                data = rest
            docx_path.write_bytes(data)
        else:
            bar = tqdm(total=total, unit="B", unit_scale=True, desc=f"Download {docx_path.name}") if tqdm and total else None  # noqa: E501
            try:
                with docx_path.open("wb") as f:
                    if first:
                        f.write(first)
                        if bar:
                            bar.update(len(first))
                    for chunk in r.iter_content(chunk_size=262144):
                        if not chunk:
                            continue
                        f.write(chunk)
                        if bar:
                            bar.update(len(chunk))
            finally:
                if bar:
                    bar.close()
        print(f"Saved DOCX to {docx_path}")
    except Exception as e:
        # Non-fatal: keep other outputs even if export fails
        print(f"Warning: failed to export DOCX: {e}")

    # 7) Optionally capture Step Functions execution history
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

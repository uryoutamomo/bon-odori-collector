"""Create an encrypted, reproducible input bundle for R2 projection comparison.

The bundle deliberately contains the master database and its manifest, so it must
never be uploaded in plaintext.  This module validates all inputs before asking
OpenSSL CMS to encrypt a temporary tarball to an X.509 recipient certificate.
Only the resulting CMS DER file is written to the requested output path.
"""

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path


class CaptureError(RuntimeError):
    """An input or encryption precondition was not satisfied."""


REQUIRED_SUPPLEMENTAL_INPUTS = (
    "data/event_date_predictions.json",
    "data/event_date_update_candidates.json",
    "data/public_event_overrides.json",
    "data/public_fixed_date_rules.json",
    "data/song_master_initial_registration.json",
    "data/rdb_song_review_source.json",
    "data/public/event_song_occurrences_public.json",
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path, description):
    path = Path(path)
    if not path.is_file():
        raise CaptureError(f"{description} is missing: {path}")
    return path


def load_manifest(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError(f"manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CaptureError("manifest must contain a JSON object")
    checksum = payload.get("database_checksum")
    if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise CaptureError("manifest database_checksum must be a lowercase SHA-256 hex value")
    return payload


def verify_sqlite_integrity(db_path):
    try:
        uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise CaptureError(f"SQLite integrity check failed to run: {exc}") from exc
    if rows != ["ok"]:
        raise CaptureError("SQLite integrity check did not return ok")


def git_sha(repository):
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CaptureError(f"could not resolve git SHA for {repository}") from exc
    value = result.stdout.strip()
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise CaptureError("git did not return a full commit SHA")
    return value


def repository_root(repository):
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CaptureError(f"could not resolve repository root for {repository}") from exc
    return Path(result.stdout.strip()).resolve()


def git_blob_matches_head(repository, path, relative_path):
    try:
        expected = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", f"HEAD:{relative_path}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        actual = subprocess.run(
            ["git", "-C", str(repository), "hash-object", str(path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CaptureError(f"supplemental input is not present in HEAD: {relative_path}") from exc
    if actual != expected:
        raise CaptureError(f"supplemental input differs from HEAD: {relative_path}")


def validate_recipient_certificate(openssl, certificate):
    try:
        subprocess.run(
            [openssl, "x509", "-in", str(certificate), "-noout"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise CaptureError(f"OpenSSL executable is unavailable: {openssl}") from exc
    except subprocess.CalledProcessError as exc:
        raise CaptureError("recipient certificate is not a valid PEM X.509 certificate") from exc


def validate_today(value):
    try:
        return dt.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise CaptureError("today must be an ISO date (YYYY-MM-DD)") from exc


def validate_target_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise CaptureError("target year must be an integer") from exc
    if not 2000 <= year <= 2100:
        raise CaptureError("target year must be between 2000 and 2100")
    return year


def reject_sqlite_sidecars(db_path):
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{db_path}{suffix}")
        if sidecar.exists():
            raise CaptureError(f"database sidecar is present; checkpoint it before capture: {sidecar.name}")


def required_supplemental_paths(repository, raw_paths):
    supplied = [Path(value).resolve() for value in raw_paths]
    expected = [(relative, (repository / relative).resolve()) for relative in REQUIRED_SUPPLEMENTAL_INPUTS]
    if len(supplied) != len(expected) or set(supplied) != {path for _, path in expected}:
        raise CaptureError("exactly the seven required supplemental JSON inputs must be supplied")
    return expected


def capture(args):
    db_path = require_file(args.db, "database")
    manifest_path = require_file(args.manifest, "manifest")
    certificate_path = require_file(args.recipient_cert, "recipient certificate")
    output_path = Path(args.output)
    if output_path.exists():
        raise CaptureError(f"refusing to overwrite output: {output_path}")

    today = validate_today(args.today)
    target_year = validate_target_year(args.target_year)
    repository = Path(args.repo)
    if not repository.is_dir():
        raise CaptureError(f"repository is missing: {repository}")
    repository = repository_root(repository)
    commit = git_sha(repository)
    validate_recipient_certificate(args.openssl, certificate_path)
    reject_sqlite_sidecars(db_path)
    supplemental_paths = required_supplemental_paths(repository, args.input)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r2-projection-inputs-") as temp_dir:
        temp_dir = Path(temp_dir)
        copied_db = temp_dir / "bon_odori_master.sqlite"
        copied_manifest = temp_dir / "bon_odori_master_manifest.json"
        shutil.copyfile(db_path, copied_db)
        shutil.copyfile(manifest_path, copied_manifest)
        copied_supplemental = []
        for relative_path, input_path in supplemental_paths:
            input_path = require_file(input_path, "supplemental input")
            copied = temp_dir / input_path.name
            shutil.copyfile(input_path, copied)
            try:
                json.loads(copied.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CaptureError(f"supplemental input is not valid JSON: {relative_path}") from exc
            git_blob_matches_head(repository, copied, relative_path)
            copied_supplemental.append((relative_path, copied, sha256(copied)))

        manifest = load_manifest(copied_manifest)
        database_hash = sha256(copied_db)
        if database_hash != manifest["database_checksum"]:
            raise CaptureError("database SHA-256 does not match manifest database_checksum")
        verify_sqlite_integrity(copied_db)
        metadata = {
            "format": "bon-odori-public-projection-inputs-v1",
            "git_sha": commit,
            "today": today,
            "target_year": target_year,
            "inputs": {
                "database": {"path": "master/bon_odori_master.sqlite", "sha256": database_hash},
                "manifest": {"path": "master/bon_odori_master_manifest.json", "sha256": sha256(copied_manifest)},
                "supplemental_json": [
                    {"path": relative_path, "sha256": digest}
                    for relative_path, _, digest in copied_supplemental
                ],
            },
        }
        plaintext = temp_dir / "inputs.tar.gz"
        encrypted = temp_dir / "inputs.cms"
        with tarfile.open(plaintext, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            archive.add(copied_db, arcname="master/bon_odori_master.sqlite", recursive=False)
            archive.add(copied_manifest, arcname="master/bon_odori_master_manifest.json", recursive=False)
            for relative_path, copied, _ in copied_supplemental:
                archive.add(copied, arcname=relative_path, recursive=False)
            encoded = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            info = tarfile.TarInfo("bundle-metadata.json")
            info.size = len(encoded)
            info.mtime = 0
            archive.addfile(info, fileobj=io.BytesIO(encoded))
        try:
            subprocess.run(
                [
                    args.openssl,
                    "cms",
                    "-encrypt",
                    "-binary",
                    "-outform",
                    "DER",
                    "-aes-256-cbc",
                    "-in",
                    str(plaintext),
                    "-out",
                    str(encrypted),
                    "-recip",
                    str(certificate_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise CaptureError("OpenSSL CMS encryption failed") from exc
        if not encrypted.is_file() or encrypted.stat().st_size == 0:
            raise CaptureError("OpenSSL CMS encryption did not produce output")
        os.replace(encrypted, output_path)
    return {"output": str(output_path)}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--input", action="append", default=[], help="required supplemental JSON input (repeatable)")
    parser.add_argument("--today", required=True)
    parser.add_argument("--target-year", required=True)
    parser.add_argument("--recipient-cert", required=True, help="PEM X.509 certificate containing the recipient public key")
    parser.add_argument("--output", required=True, help="new CMS DER output path")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--openssl", default="openssl")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        capture(args)
    except CaptureError as exc:
        raise SystemExit(f"capture failed: {exc}") from exc
    print(f"encrypted comparison-input bundle written: {args.output}")


if __name__ == "__main__":
    main()

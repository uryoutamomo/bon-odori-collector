#!/usr/bin/env python3
"""Production adapters for the default-off review inbox shadow runner.

Importing this module has no side effects.  The S3 adapter delegates to the
existing master DB artifact functions and never exposes a force-publish path.
"""

from __future__ import annotations

import hashlib
import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import master_rdb.master_db as master_db
from master_rdb import s3_artifact
from export_public_events import (
    build_public_events_from_master,
    project_public_events,
)
from review_inbox_adapters.source_writer import ArtifactState, SourceWriterError


class MasterDbS3ArtifactStore:
    """Adapt master_db_s3_artifact functions to the ArtifactStore protocol."""

    def __init__(
        self,
        *,
        bucket: str = "",
        prefix: str = "",
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self.client = client

    def _namespace(self, db: Path, manifest: Path, **overrides: Any) -> Namespace:
        values = {
            "bucket": self.bucket,
            "prefix": self.prefix,
            "db": Path(db),
            "manifest": Path(manifest),
        }
        values.update(overrides)
        return Namespace(**values)

    @staticmethod
    def _manifest_path(database: Path) -> Path:
        return Path(database).with_suffix(".manifest.json")

    def status(self) -> ArtifactState:
        # status only uses db for a local diagnostic checksum.  A deliberately
        # missing path prevents it from confusing a repo-local DB with remote.
        missing_local = Path(".review-inbox-remote-status-only.sqlite")
        result = s3_artifact.status(
            self._namespace(missing_local, missing_local.with_suffix(".manifest.json")),
            client=self.client,
        )
        checksum = str(result.get("remote_checksum") or "")
        snapshot_id = str(result.get("remote_snapshot_id") or "")
        if not result.get("remote_exists") or not checksum or not snapshot_id:
            raise SourceWriterError("remote master DB status is incomplete")
        return ArtifactState(checksum=checksum, snapshot_id=snapshot_id)

    def fetch(self, destination: Path) -> None:
        destination = Path(destination)
        result = s3_artifact.fetch(
            self._namespace(
                destination,
                self._manifest_path(destination),
                overwrite=False,
            ),
            client=self.client,
        )
        if str(result.get("database_checksum") or "") == "":
            raise SourceWriterError("master DB fetch returned no checksum")

    def publish(self, source: Path, *, expected_remote_checksum: str) -> ArtifactState:
        if not expected_remote_checksum:
            raise SourceWriterError("CAS publication requires expected_remote_checksum")
        source = Path(source)
        result = s3_artifact.publish(
            self._namespace(
                source,
                self._manifest_path(source),
                snapshot_id="",
                expect_remote_checksum=expected_remote_checksum,
                force=False,
            ),
            client=self.client,
        )
        published_checksum = str(result.get("database_checksum") or "")
        state = self.status()
        if state.checksum != published_checksum:
            raise SourceWriterError("published checksum does not match remote status")
        return state


def build_public_projection(
    db_path: Path, *, target_year: int, today: str
) -> list[dict[str, Any]]:
    """Build the production events_public.json content without writing files."""

    events, _covered, _fallback, _skipped = build_public_events_from_master(
        db_path, target_year=target_year
    )
    return project_public_events(
        events, target_year=target_year, db_path=db_path, today=today
    )["public_events"]


def public_projection_digest(db_path: Path, *, target_year: int, today: str) -> str:
    """Return the SHA-256 of the exact events_public.json content bytes."""

    projection = build_public_projection(
        Path(db_path), target_year=target_year, today=today
    )
    output_bytes = json.dumps(projection, ensure_ascii=False, indent=2).encode("utf-8")
    return hashlib.sha256(output_bytes).hexdigest()

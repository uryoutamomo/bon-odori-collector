"""Compatibility CLI for master RDB S3 artifact operations.

The implementation lives in :mod:`master_rdb.s3_artifact`; this wrapper keeps
documented workflow and manual commands stable.
"""

from master_rdb.s3_artifact import *  # noqa: F401,F403
from master_rdb.s3_artifact import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility CLI for unified-model v2 audits."""

from master_rdb.unified_model_audit import *  # noqa: F401,F403
from master_rdb.unified_model_audit import main


if __name__ == "__main__":
    raise SystemExit(main())

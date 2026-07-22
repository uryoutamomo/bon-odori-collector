"""Compatibility CLI for Master RDB freeze-policy operations."""

from master_rdb.freeze_policy import *  # noqa: F401,F403
from master_rdb.freeze_policy import main


if __name__ == "__main__":
    raise SystemExit(main())

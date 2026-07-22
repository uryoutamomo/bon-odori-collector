"""Compatibility CLI for Master RDB audits."""

from master_rdb.audit import *  # noqa: F401,F403
from master_rdb.audit import main


if __name__ == "__main__":
    raise SystemExit(main())

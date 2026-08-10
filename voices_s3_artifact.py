"""Compatibility CLI for the voices S3 artifact."""
from collection_support.voices_s3_artifact import *  # noqa: F401,F403
from collection_support.voices_s3_artifact import main

if __name__ == "__main__":
    raise SystemExit(main())

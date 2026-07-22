"""Compatibility CLI for active-channel YouTube video review."""

from youtube_channels.active_video_review import *  # noqa: F401,F403
from youtube_channels.active_video_review import main


if __name__ == "__main__":
    raise SystemExit(main())

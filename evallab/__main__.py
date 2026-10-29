"""Entry point: python -m evallab <command>. Loads .env before anything reads the settings."""

import sys

from dotenv import load_dotenv

load_dotenv()

from .cli import main  # noqa: E402  (must come after load_dotenv so CLAUDE_MODEL is picked up)

sys.exit(main())

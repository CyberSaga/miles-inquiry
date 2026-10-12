"""Allow ``python -m miles_inquiry``."""
import sys

from .cli import main

sys.exit(main())

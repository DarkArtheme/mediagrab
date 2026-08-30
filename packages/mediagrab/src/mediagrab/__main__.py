"""Allow ``python -m mediagrab`` as an alias for the ``mediagrab`` script."""

import sys

from mediagrab.cli import main

sys.exit(main())

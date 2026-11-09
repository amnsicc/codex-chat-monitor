"""Native watcher signal; never reads session content."""
import sys
from pathlib import Path
Path(sys.argv[1]).touch()

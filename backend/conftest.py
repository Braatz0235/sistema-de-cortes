import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway storage dir before anything imports app.config,
# so tests never touch the real storage/videos directory.
_TEST_STORAGE = Path(tempfile.mkdtemp(prefix="cortes-test-storage-"))
os.environ.setdefault("STORAGE_DIR", str(_TEST_STORAGE))

sys.path.insert(0, str(Path(__file__).resolve().parent))

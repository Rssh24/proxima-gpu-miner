"""Safe, portable test paths. Import before any miner runtime module."""
import contextlib
import os
from pathlib import Path
import shutil
import sys
import tempfile

SOURCE = Path(os.environ.get('PROXIMA_SOURCE_ROOT', Path(__file__).resolve().parents[1])).resolve()
PACKAGE = Path(os.environ.get('PROXIMA_PACKAGE_ROOT', SOURCE)).resolve()
MINER = PACKAGE / 'miner'
if not (MINER / 'paths.py').is_file():
    raise RuntimeError('No miner source found; supply --source-root or --package-root.')
SCRATCH = (SOURCE / 'build' / 'test-work').resolve()
SCRATCH.mkdir(parents=True, exist_ok=True)
# Always override inherited user data before importing paths, including when a
# developer happens to have a real wallet environment variable in their shell.
os.environ['PROXIMA_MINER_DATA'] = str(SCRATCH / 'unused-synthetic-default')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
sys.path.insert(0, str(MINER))


@contextlib.contextmanager
def temporary_directory(prefix='fixture-'):
    root = Path(tempfile.mkdtemp(prefix=prefix, dir=SCRATCH)).resolve()
    if root == SCRATCH or not root.is_relative_to(SCRATCH):
        raise RuntimeError('Unexpected test fixture path')
    try:
        yield str(root)
    finally:
        target = root.resolve()
        if target == SCRATCH or not target.is_relative_to(SCRATCH):
            raise RuntimeError('Refusing cleanup outside test scratch directory')
        shutil.rmtree(target)

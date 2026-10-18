"""Application files are immutable; recipient data stays in LocalAppData."""
import os
from pathlib import Path
APP_ROOT=Path(__file__).resolve().parents[1]
override=os.environ.get('PROXIMA_MINER_DATA')
if override:
    DATA_ROOT=Path(override).expanduser().resolve()
else:
    local=os.environ.get('LOCALAPPDATA')
    if not local:raise RuntimeError('LOCALAPPDATA is unavailable; launch from a normal Windows user account')
    DATA_ROOT=Path(local)/'ProximaGpuMinerBeta'/'take1'

def ensure_data_dirs():
    for name in ('','logs','work'):(DATA_ROOT/name).mkdir(parents=True,exist_ok=True)

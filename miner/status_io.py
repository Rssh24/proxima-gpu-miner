"""Publish public status atomically despite short Windows reader locks."""
import json
import errno
import os
import tempfile
import time
from pathlib import Path

RETRY_DELAYS = (.005, .015, .04, .08)

def _sharing_error(error):
    # Python's Windows CRT file opens may expose a sharing lock as EACCES
    # without winerror; native replace() exposes WinError5/32/33 directly.
    return (getattr(error, 'winerror', None) in (5, 32, 33) or
            (os.name == 'nt' and error.errno == errno.EACCES))

def write_status(path, snapshot, stop_event=None):
    """False means a transient lock; retain the last complete published status.

    The supervisor's existing stale-status watchdog remains authoritative.
    Other IO failures still propagate. Private wallet data is never handled.
    """
    path = Path(path)
    payload = json.dumps(snapshot)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=path.stem+'-', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(payload)
        for attempt in range(len(RETRY_DELAYS)+1):
            try:
                temporary.replace(path)
                return True
            except OSError as error:
                if not _sharing_error(error):
                    raise
                if attempt == len(RETRY_DELAYS):
                    return False
                if stop_event is None:
                    time.sleep(RETRY_DELAYS[attempt])
                elif stop_event.wait(RETRY_DELAYS[attempt]):
                    return False
    except OSError as error:
        if _sharing_error(error):
            return False
        raise
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # A scanner may still hold the temporary file. Never let cleanup
                # turn a successfully published status into a miner failure.
                pass

def append_diagnostic(path, snapshot):
    """Optional history may be skipped on a lock; never replay a partial append."""
    payload = json.dumps(snapshot)+'\n'
    try:
        with Path(path).open('a', encoding='utf-8') as output:
            output.write(payload)
        return True
    except OSError as error:
        if _sharing_error(error):
            return False
        raise

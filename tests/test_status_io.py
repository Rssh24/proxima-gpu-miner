"""Real Windows file-sharing tests on isolated fixtures, never production data."""
import ctypes as C
import json
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
from bootstrap import MINER, temporary_directory
import status_io

if os.name == 'nt':
    kernel = C.WinDLL('kernel32.dll', use_last_error=True)
    kernel.CreateFileW.argtypes = [C.c_wchar_p,C.c_ulong,C.c_ulong,C.c_void_p,C.c_ulong,C.c_ulong,C.c_void_p]
    kernel.CreateFileW.restype = C.c_void_p
    kernel.CloseHandle.argtypes = [C.c_void_p]
    kernel.CloseHandle.restype = C.c_int


def lock_file(path, share=3):
    handle = kernel.CreateFileW(str(path), 0x80000000, share, None, 3, 0x80, None)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    return handle


@unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics required')
class StatusIOTests(unittest.TestCase):
    def setUp(self):
        self.fixture = temporary_directory('status-')
        self.root = Path(self.fixture.__enter__())
        self.path = self.root/'status.json'
        self.path.write_text('{"n":0}', encoding='utf-8')

    def tearDown(self):
        self.fixture.__exit__(None, None, None)

    def test_sharing_failure_preserves_old_json_and_cleans_temp(self):
        handle = lock_file(self.path)
        try:
            start = time.perf_counter()
            self.assertFalse(status_io.write_status(self.path, {'n':1}))
            self.assertLess(time.perf_counter()-start, .7)
            self.assertEqual(json.loads(self.path.read_text()), {'n':0})
            self.assertFalse(list(self.root.glob('*.tmp')))
        finally:
            kernel.CloseHandle(handle)
        self.assertTrue(status_io.write_status(self.path, {'n':2,'text':'Unicode \u2603'}))
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['text'], 'Unicode \u2603')

    def test_stop_event_cancels_retries(self):
        handle = lock_file(self.path)
        try:
            stopped = threading.Event(); stopped.set(); start = time.perf_counter()
            self.assertFalse(status_io.write_status(self.path, {'n':1}, stopped))
            self.assertLess(time.perf_counter()-start, .15)
        finally:
            kernel.CloseHandle(handle)

    def test_permanent_disk_failure_propagates(self):
        failure = OSError('synthetic disk-full error'); failure.winerror = 112
        with patch.object(Path, 'replace', side_effect=failure):
            with self.assertRaises(OSError) as caught:
                status_io.write_status(self.path, {'n':1})
        self.assertIs(caught.exception, failure)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_concurrent_readers_never_see_partial_json(self):
        done = threading.Event(); errors = []; reads = []
        def reader():
            while not done.is_set():
                try:
                    with self.path.open('r', encoding='utf-8') as handle:
                        value=json.load(handle); time.sleep(.001)
                    if not isinstance(value['n'], int):
                        raise ValueError('invalid snapshot')
                    reads.append(value['n'])
                except OSError as exc:
                    if not status_io._sharing_error(exc): errors.append(str(exc))
                except Exception as exc:
                    errors.append(str(exc))
                done.wait(.001)
        thread = threading.Thread(target=reader); thread.start()
        try:
            for n in range(1,201): status_io.write_status(self.path, {'n':n})
        finally:
            done.set(); thread.join(3)
        self.assertFalse(thread.is_alive()); self.assertTrue(reads); self.assertEqual(errors, [])
        self.assertTrue(status_io.write_status(self.path, {'n':201}))
        self.assertEqual(json.loads(self.path.read_text())['n'],201)

    def test_optional_history_skips_locked_sample_without_replay(self):
        path = self.root/'telemetry.jsonl'; path.write_text('old\n')
        handle = lock_file(path, share=1)
        try: self.assertFalse(status_io.append_diagnostic(path, {'n':1}))
        finally: kernel.CloseHandle(handle)
        self.assertEqual(path.read_text(), 'old\n')
        self.assertTrue(status_io.append_diagnostic(path, {'n':2}))
        lines = path.read_text().splitlines()
        self.assertEqual(lines[0], 'old'); self.assertEqual(json.loads(lines[1]), {'n':2})


if __name__ == '__main__': unittest.main(verbosity=2)

"""Run CPU-only mocked regression tests. Never marks GPU validation passed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--package-root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    source = args.source_root.resolve()
    os.environ['PROXIMA_SOURCE_ROOT'] = str(source)
    if args.package_root:
        os.environ['PROXIMA_PACKAGE_ROOT'] = str(args.package_root.resolve())
    else:
        os.environ.pop('PROXIMA_PACKAGE_ROOT', None)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import bootstrap
    started = time.monotonic()
    loader = unittest.TestLoader()
    suite = loader.discover(str(Path(__file__).resolve().parent), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        'schema_version': 1, 'suite': 'cpu-only-regression',
        'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors),
        'skipped': len(result.skipped), 'elapsed_seconds': round(time.monotonic()-started, 3),
        'gpu_executed': False, 'gpu_validated': False,
        'real_wallet_accessed': False, 'public_network_used': False,
        'miner_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(bootstrap.MINER.glob('*.py'))},
    }
    if args.output:
        output = args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())

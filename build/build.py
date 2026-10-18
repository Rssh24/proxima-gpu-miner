"""Portable Windows source builder. It never validates a GPU or starts mining."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def run(args: list[str], *, cwd: Path, env: dict[str, str], capture=False) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ''


def tool(name: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return str(Path(resolved).resolve())
    path = Path(name).expanduser()
    if path.is_file():
        return str(path.resolve())
    raise RuntimeError(f'Required tool was not found: {name}')


def verify_upstream(source: Path, lock: dict) -> None:
    root = source / 'upstream'
    inventory = json.loads((source / 'build' / 'upstream-files.json').read_text(encoding='utf-8'))
    if inventory.get('commit') != lock['upstream']['commit']:
        raise RuntimeError('The upstream file lock belongs to another commit.')
    expected = inventory['files']
    actual = {p.relative_to(root).as_posix(): p for p in root.rglob('*')
              if p.is_file() and '.git' not in p.relative_to(root).parts}
    if set(actual) != set(expected):
        raise RuntimeError('The upstream tree differs from the pinned archive (missing or extra files).')
    for relative, entry in expected.items():
        data = actual[relative].read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()
        if blob != entry['git_blob_sha1']:
            raise RuntimeError(f'Pinned upstream source differs: {relative}')
    for name in ('go.mod', 'go.sum'):
        if digest(root / name) != lock['upstream'][name.replace('.', '_') + '_sha256']:
            raise RuntimeError(f'Pinned dependency lock differs: {name}')


def acquire_runtime(source: Path, work: Path, lock: dict, home: str | None,
                    download: bool, offline: bool, env: dict[str, str]) -> Path:
    candidates = [Path(home).expanduser()] if home else [source / 'runtime' / 'python']
    for candidate in candidates:
        if (candidate / 'python.exe').is_file():
            runtime = candidate.resolve()
            break
    else:
        if not download:
            raise RuntimeError('Supply --python-home with the embedded Python runtime, or explicitly use --download-runtime.')
        if offline:
            raise RuntimeError('--offline and --download-runtime cannot be combined.')
        pin = lock['python_embed']
        if not pin['url'].startswith('https://www.python.org/ftp/python/'):
            raise RuntimeError('Runtime URL is not the pinned official Python host.')
        downloads = work / 'downloads'
        downloads.mkdir(parents=True, exist_ok=True)
        archive = downloads / ('python-' + pin['version'] + '-embed-amd64.zip')
        if not archive.exists():
            print('Downloading the explicitly requested, pinned official Python runtime...')
            temporary = archive.with_suffix('.zip.partial')
            with urllib.request.urlopen(pin['url'], timeout=60) as response, temporary.open('wb') as output:
                shutil.copyfileobj(response, output)
            if digest(temporary) != pin['sha256']:
                raise RuntimeError('Downloaded Python archive checksum does not match the pin.')
            os.replace(temporary, archive)
        if digest(archive) != pin['sha256']:
            raise RuntimeError('Cached Python archive checksum does not match the pin.')
        runtime = downloads / ('python-' + pin['version'])
        runtime.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                destination = (runtime / member.filename).resolve()
                if not destination.is_relative_to(runtime.resolve()):
                    raise RuntimeError('Unsafe path in the Python runtime archive.')
            bundle.extractall(runtime)
    for required in ('python.exe', 'python313.dll', 'python313.zip'):
        if not (runtime / required).is_file():
            raise RuntimeError('PythonHome must be the Python 3.13.7 x64 embedded runtime directory.')
    version = run([str(runtime / 'python.exe'), '-c',
                   "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
                  cwd=source, env=env, capture=True)
    if version != lock['python_embed']['version']:
        raise RuntimeError('The distributable runtime must match pinned Python ' + lock['python_embed']['version'])
    return runtime


def copy_runtime(runtime: Path, output: Path, source: Path) -> None:
    target = output / 'tools' / 'python'
    target.mkdir(parents=True, exist_ok=True)
    allowed = {'.exe', '.dll', '.pyd', '.zip', '.cat', '.txt'}
    for item in runtime.iterdir():
        if item.is_file() and item.suffix.lower() in allowed:
            shutil.copy2(item, target / item.name)
    template = source / 'runtime' / 'python313._pth'
    content = template.read_text(encoding='utf-8-sig') if template.exists() else 'python313.zip\n.\n..\\..\\miner\n..\\..\\scripts\n'
    (target / 'python313._pth').write_text(content, encoding='utf-8')


def copy_public_sources(source: Path, output: Path) -> dict[str, str]:
    source_hashes = {}
    for directory in ('app', 'miner'):
        for path in sorted((source / directory).rglob('*')):
            if not path.is_file() or path.suffix.lower() not in {'.go', '.py', '.cl', '.c', '.h', '.txt'}:
                continue
            if '__pycache__' in path.parts:
                continue
            relative = path.relative_to(source)
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if path.suffix.lower() in {'.go', '.py', '.cl', '.c', '.h'}:
                source_hashes[relative.as_posix()] = digest(path)
    fixture = Path('upstream/util/vrf/vrf_test.go')
    target = output / fixture
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / fixture, target)
    source_hashes[fixture.as_posix()] = digest(source / fixture)
    shutil.copy2(source / 'LICENSE.txt', output / 'LICENSE.txt')
    assets = source / 'assets'
    for name in ('launch.json', 'README.txt'):
        shutil.copy2(assets / name, output / name)
    for directory in ('scripts', 'licenses'):
        if (assets / directory).is_dir():
            shutil.copytree(assets / directory, output / directory)
    # Historical release validation records are deliberately not copied.
    return source_hashes


def refresh_dependency_record(output: Path, source: Path, go: str,
                              env: dict[str, str], lock: dict) -> None:
    """Bind shipped license inventory to these exact rebuilt binaries."""
    path = output / 'licenses' / 'dependencies.json'
    record = json.loads(path.read_text(encoding='utf-8'))
    def dependencies(metadata: str) -> set[tuple[str, ...]]:
        return {tuple(line.split()[1:]) for line in metadata.splitlines()
                if line.strip().startswith('dep\t')}
    for name, previous in record['native_artifacts'].items():
        binary = output / 'tools' / name
        metadata = run([go, 'version', '-m', str(binary)], cwd=source, env=env, capture=True)
        lines = metadata.splitlines()
        lines[0] = 'tools/' + name + ': ' + lock['go_version']
        metadata = '\n'.join(lines) + '\n'
        if dependencies(metadata) != dependencies(previous['build_info']):
            raise RuntimeError('Linked dependencies changed; refresh reviewed license inventory: ' + name)
        previous.update(sha256=digest(binary), size_bytes=binary.stat().st_size,
                        build_info=metadata)
    record.update(release=lock['version'], source_commit=lock['upstream']['commit'],
                  go_version=run([go, 'version'], cwd=source, env=env, capture=True),
                  build_time_unix=int(dt.datetime.now(dt.timezone.utc).timestamp()))
    write_json(path, record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--go', default='go')
    parser.add_argument('--python-home')
    parser.add_argument('--output')
    parser.add_argument('--go-mod-cache')
    parser.add_argument('--go-cache')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--download-runtime', action='store_true')
    parser.add_argument('--skip-tests', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('This build entry point targets Windows x64. Run it on Windows.')
    source = Path(args.source_root).expanduser().resolve()
    lock = json.loads((source / 'build' / 'source-lock.json').read_text(encoding='utf-8'))
    output = Path(args.output).expanduser().resolve() if args.output else source / 'out' / lock['version']
    for protected in ('app', 'miner', 'upstream', 'tests', 'assets', 'runtime', 'build'):
        if output == source / protected or output.is_relative_to(source / protected):
            raise RuntimeError('Output must not overwrite a source/tooling directory.')
    if output == source or (output.exists() and any(output.iterdir())):
        raise RuntimeError('Output must be a new or empty directory. Existing files are never deleted.')
    work = source / 'build' / 'work'
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH', 'PROXIMA_KEY_PASSPHRASE', 'NONCE_SEEKER_SEED'):
        env.pop(name, None)
    env.update(GOTOOLCHAIN='local', GOTELEMETRY='off', GOWORK='off', GO111MODULE='on',
               GOFLAGS='', CGO_ENABLED='0', GOOS='windows', GOARCH='amd64',
               PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               GOCACHE=str(Path(args.go_cache).expanduser().resolve() if args.go_cache else work / 'go-cache'), GOPATH=str(work / 'go-path'),
               GOMODCACHE=str(Path(args.go_mod_cache).expanduser().resolve() if args.go_mod_cache else work / 'go-mod-cache'),
               TEMP=str(work), TMP=str(work), PROXIMA_MINER_DATA=str(work / 'isolated-test-data'))
    if args.offline:
        env.update(GOPROXY='off', GOSUMDB='off')
    go = tool(args.go)
    go_version = run([go, 'version'], cwd=source, env=env, capture=True)
    if lock['go_version'] not in go_version.split():
        raise RuntimeError('Use the pinned Go toolchain ' + lock['go_version'] + '; automatic toolchain downloads are disabled.')
    print('Verifying the pinned upstream archive and dependency locks...')
    verify_upstream(source, lock)
    runtime = acquire_runtime(source, work, lock, args.python_home, args.download_runtime, args.offline, env)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'tools').mkdir(exist_ok=True)
    sources = copy_public_sources(source, output)
    copy_runtime(runtime, output, source)
    common = [go, 'build', '-trimpath', '-buildvcs=false', '-mod=readonly']
    print('Building five native binaries...')
    run(common + ['-ldflags=-H=windowsgui', '-o', str(output / 'Proxima-Miner.exe'), str(source / 'app' / 'main.go')], cwd=source, env=env)
    run(common + ['-ldflags=-H=windowsgui', '-o', str(output / 'Wallet-Balance.exe'), str(source / 'app' / 'balance.go')], cwd=source, env=env)
    identity = '-X github.com/lunfardo314/proxima/global.CommitHash=' + lock['upstream']['commit'] + ' -X github.com/lunfardo314/proxima/global.CommitTime=' + lock['upstream']['commit_time_utc']
    run(common + ['-ldflags=' + identity, '-o', str(output / 'tools' / 'proxi.exe'), './proxi'], cwd=source / 'upstream', env=env)
    run(common + ['-o', str(output / 'tools' / 'oracle.exe'), str(source / 'miner' / 'oracle.go')], cwd=source / 'upstream', env=env)
    run(common + ['-o', str(output / 'tools' / 'gpu-seeker.exe'), str(source / 'miner' / 'launcher.go')], cwd=source, env=env)
    run([go, 'mod', 'verify'], cwd=source / 'upstream', env=env)
    artifacts = {relative: digest(output / relative) for relative in
                 ('Proxima-Miner.exe', 'Wallet-Balance.exe', 'tools/proxi.exe', 'tools/oracle.exe', 'tools/gpu-seeker.exe')}
    refresh_dependency_record(output, source, go, env, lock)
    seeker = {Path(name).name: value for name, value in sources.items()
              if name.startswith('miner/') and Path(name).suffix in {'.py', '.cl'}}
    info = {'version': lock['version'] + '-source-build', 'source_commit': lock['upstream']['commit'],
            'miner_version': 4, 'artifacts': {name: artifacts['tools/' + name] for name in
                                           ('proxi.exe', 'oracle.exe', 'gpu-seeker.exe')},
            'seeker_sources': seeker, 'build_kind': 'source-rebuild'}
    write_json(output / 'tools' / 'build-info.json', info)
    validation = dict(info, validation_passed=False,
                      validation_scope='Unvalidated source rebuild. Run the explicit selected-GPU proof and local-protocol validation workflow.')
    write_json(output / 'tools' / 'compatibility-validation.json', validation)
    baseline = lock.get('release_sources', {})
    modified = sources != baseline
    manifest = {'schema_version': 1, 'version': info['version'], 'source_commit': info['source_commit'],
                'go_version': go_version, 'python_version': lock['python_embed']['version'],
                'source_sha256': sources, 'artifact_sha256': artifacts,
                'source_modified_from_release': modified, 'validation_passed': False,
                'cpu_tests': 'not run'}
    write_json(output / 'build-manifest.json', manifest)
    if not args.skip_tests:
        runner = source / 'tests' / 'Run-Tests.ps1'
        if not runner.is_file():
            raise RuntimeError('CPU-only test runner is missing; artifacts remain unvalidated.')
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        run([str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(runner),
             '-Python', str(output / 'tools/python/python.exe'), '-SourceRoot', str(source),
             '-PackageRoot', str(output), '-Output', str(output / 'cpu-test-results.json')], cwd=source, env=env)
        manifest['cpu_tests'] = 'passed; no GPU/device validation claimed'
        write_json(output / 'build-manifest.json', manifest)
    print('Build complete. Artifacts are UNVALIDATED and GPU setup/mining remains gated.')
    print('Run build/Validate.ps1 explicitly for selected-GPU proofs and the official local protocol test.')
    print('Output: ' + str(output))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print('Build failed: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)




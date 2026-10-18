# Building and testing

The build creates a separate Windows runtime package from this source tree. It does not read an installed miner's wallet, start live mining, or apply GPU-driver settings. A newly built package remains **unvalidated** until the explicit local GPU/protocol validation succeeds.

## Prerequisites

- Windows 11, x64.
- Go **1.26.6**, Windows amd64, available as `go` or supplied with `-Go`. The upstream module also records this toolchain. Download from <https://go.dev/dl/>.
- Python **3.11 or newer** to run the build tooling, available as `python` or supplied with `-Python`.
- The **CPython 3.13.7 Windows amd64 embedded runtime** for the resulting package. Its official URL and expected archive SHA-256 are pinned in `runtime/python-runtime.json` and `build/source-lock.json`. The [official Python release page](https://www.python.org/downloads/release/python-3137/) also provides the runtime and upstream sources.
- Network access for uncached Go modules. The module versions and checksums are preserved in `upstream/go.mod` and `upstream/go.sum`.

No OpenCL SDK or GPU driver is needed just to compile the application and run synthetic CPU tests. A supported AMD/NVIDIA GPU and its vendor driver are required for the later GPU validation and mining steps. The app's Python code uses the standard library and `ctypes`; there is no pip dependency installation step.

Run the following commands from the root of this source tree in PowerShell. An explicit executable path can replace `go` or `python` if several versions are installed.

```powershell
$PythonExe = (Get-Command python).Source
$GoExe = (Get-Command go).Source
```

## Build a fresh package

To allow the builder to download the pinned embedded Python archive from its official URL:

```powershell
.\build\Build.ps1 -Go $GoExe -Python $PythonExe -DownloadRuntime
```

The runtime is not downloaded unless `-DownloadRuntime` is explicitly supplied. To use an already extracted copy instead:

```powershell
.\build\Build.ps1 -PythonHome 'C:\BuildTools\python-3.13.7-embed-amd64'
```

The default output is `out/windows-beta-0.1.1`. The output path must be new or empty. Use `-OutputDirectory` for another clean directory; do not target an installed user's miner or personal data folder. For example:

```powershell
.\build\Build.ps1 -Go 'C:\BuildTools\go\bin\go.exe' `
  -Python 'C:\BuildTools\python\python.exe' `
  -PythonHome 'C:\BuildTools\python-3.13.7-embed-amd64' `
  -OutputDirectory '.\out\my-build'
```

By default the build runs the CPU-only regression suite. `-SkipTests` is available for development, but a skipped suite is not validation. `build/build.py` exposes the corresponding `--go`, `--python-home`, `--output`, `--go-mod-cache`, `--offline`, `--download-runtime`, and `--skip-tests` arguments.

### Offline build

Prepare the exact embedded runtime and a Go module cache containing the pinned upstream dependencies beforehand. There is no promise that an empty cache can build offline, and this repository does not vendor every Go module.

```powershell
.\build\Build.ps1 -Offline `
  -PythonHome 'C:\BuildTools\python-3.13.7-embed-amd64' `
  -GoModCache 'C:\BuildTools\gomodcache' `
  -OutputDirectory '.\out\offline-build'
```

`-Offline` suppresses module downloads; missing cached dependencies cause an error. Do not combine an offline build with a request to download the runtime.

## Outputs and build identity

The builder compiles five native executables:

| Output | Source |
| --- | --- |
| `Proxima-Miner.exe` | `app/main.go` |
| `Wallet-Balance.exe` | `app/balance.go` |
| `tools/proxi.exe` | Official `upstream/proxi` package |
| `tools/oracle.exe` | `miner/oracle.go`, linked with the pinned upstream module dependencies |
| `tools/gpu-seeker.exe` | `miner/launcher.go` |

It assembles the Python sources, kernel, runtime, public network configuration, scripts, and license notices into the output package. Go builds use `-trimpath -buildvcs=false` and no C toolchain. The official client's archive build supplies these linker values:

```text
-X github.com/lunfardo314/proxima/global.CommitHash=60515d0074e63e467de6d63532c1236c1bec332a
-X github.com/lunfardo314/proxima/global.CommitTime=2026-10-18T14:04:58Z
```

`build/source-lock.json` records the reference upstream/source/runtime inputs. The actual build manifest records the rebuilt source and artifact hashes. A source archive has no original Git metadata, so a correct source rebuild need not be byte-for-byte identical to a previously supplied executable. Compare the recorded inputs and validation evidence, not just a version label.

The reference records in `assets/release-validation/` describe the supplied release. They are not approval for a new build. The builder emits an unvalidated compatibility record, and setup/mining stay blocked until the validation below passes.

## CPU-only regression tests

```powershell
.\tests\Run-Tests.ps1 -Python $PythonExe
```

The runner also accepts `-SourceRoot`, `-PackageRoot`, and `-Output`. Use `-PackageRoot` to check a built runtime layout. These tests use synthetic fixtures and cover device selection/profile matching, telemetry capability handling, power/thermal logic, atomic status publication, cumulative accounting, and diagnostic privacy. They do not use your wallet, run a GPU workload, or connect to the public mining network.

## Compile the official protocol test

This step compiles an additional test executable against the pinned official source and a test overlay. It does not run the test or use the GPU:

```powershell
.\tests\Build-ProtocolTest.ps1 -Python $PythonExe -Go $GoExe `
  -GoModCache '.\build\work\go-mod-cache'
```

Optional arguments are `-SourceRoot`, `-OutputDirectory`, and `-GoModCache`. The example reuses the native builder's default module cache; if the native build used a custom `-GoModCache`, pass that same path here. The default output directory is `build/protocol`, containing `protocol-tests.exe` and `protocol-build.json`.

Protocol compilation is offline: it requires the runtime and test dependencies to be present in the supplied cache and does not download missing modules. The upstream source snapshot is kept intact. Its compile receipt is checked again when running GPU validation.

## Validate the selected GPU and rebuilt artifacts

This is an explicit **real GPU workload**. Close other GPU applications, ensure the GPU is cool, and run:

```powershell
.\build\Validate.ps1 `
  -PackageRoot '.\out\windows-beta-0.1.1' `
  -ProtocolExe '.\build\protocol\protocol-tests.exe' `
  -Device auto
```

The wrapper accepts `-Python` and `-Output` as well. `-Device auto` selects a suitable detected GPU; a device key can explicitly select another card. The validation uses isolated test data and synthetic credentials. It compares GPU results with official RFC/reference and nonce-boundary behavior and exercises the local official seeker protocol. It does not mine on the public network or read your existing wallet.

Only a successful run can mark the rebuilt compatibility record as validated. Do not edit that flag by hand or copy a validation record from another binary/source build. A failure is a failed configuration, not something to bypass.

After validation, open the built `Proxima-Miner.exe`. Click **GPU and wallet setup** for that PC's device calibration and recipient wallet, save the encrypted wallet backup and recovery password separately, then explicitly start mining. Build validation does not create a production wallet, start mining, or establish long-term stability. Each recipient still runs first-run setup.

## Making changes and publishing builds

Keep modifications in the custom source directories. The upstream snapshot is pinned; an upstream upgrade requires a deliberate new source identity and review of its network/protocol changes. Rebuild after changes to native code, Python source, or the kernel, and repeat the relevant tests and actual GPU validation. Kernel, driver, and device changes also require fresh device setup. Recipients updating to 0.1.1 must explicitly run GPU and wallet setup again; the old kernel fingerprint cannot authorize the new kernel. Setup preserves an existing wallet, recalibrates power and performance, and selects Maximum.

Before packaging, preserve license notices and covered dependency source, generate artifact/source manifests, and verify the archive against an explicit allowlist. Exclude `.git`, caches, build work, local test outputs, wallet/configuration data, recovery credentials, mining logs, device profiles, and backups. Git excludes generated runtime binaries and downloaded toolchains. Never release an installed user's data directory.

For runtime behavior, temperature thresholds, wallet recovery, and power modes, see [assets/README.txt](assets/README.txt). For components and license provenance, see [SOURCE.md](SOURCE.md).

## Native interface logic tests

These additional tests exercise the GUI and balance logic with synthetic files; they do not open application windows or start mining.

```powershell
& $PythonExe .\tests\run_go_tests.py --go $GoExe
```

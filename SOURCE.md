# Source map and provenance

This source tree accompanies Proxima GPU Miner for Windows beta 0.1.1. It includes the custom application and miner sources, build/test tooling, release assets, and the pinned official Proxima source. It contains no recipient wallet, recovery credentials, personal mining logs, or calibrated device profile.

## Layout

| Path | Contents |
| --- | --- |
| `app/` | Native Windows GUI and public balance viewer source |
| `miner/` | Python supervisor, OpenCL backend/kernel, device setup, telemetry, wallet integration, and native helper source |
| `upstream/` | Unmodified official Proxima snapshot, including its original `go.mod` and `go.sum` |
| `tests/` | Synthetic regression tests and an optional official-protocol GPU test overlay |
| `assets/` | Public network configuration, runtime guide, backup script, license notices, and reference release-validation records |
| `build/` | Portable build scripts and source/runtime locks |
| `runtime/python/` | Generated or supplied Python embedded runtime; excluded from Git |
| `UPSTREAM.json` | Pinned official repository and snapshot identity |

The source checkout itself is not the installed application. The build creates a separate runtime layout; see [BUILDING.md](BUILDING.md). Source-tree notice paths under `assets/licenses/` become `licenses/` in that runtime layout. Reference release-validation records describe the supplied release; they must not be copied to approve newly built or modified binaries.

## Custom components

| Source | Role |
| --- | --- |
| `app/main.go` | English Win32 interface, automatic GPU selection, setup/mining controls, status, local recovery-password display, and diagnostic/backup actions |
| `app/balance.go` | Read-only public account balance viewer |
| `miner/run_mining.py` | Network identity/version gate and supervised official miner lifecycle, with CPU workers disabled by the GUI |
| `miner/seeker.py` | Local external nonce-seeker protocol, GPU work scheduling, proof submission, status, and thermal/power control |
| `miner/launcher.go` | Native launcher for the Python seeker, with child-process containment and per-user working directories |
| `miner/opencl_backend.py`, `miner/vrf.cl` | OpenCL device interaction and GPU VRF computation |
| `miner/gpu_filter.py` | Host-side filtering of GPU output records before independent official-oracle checks |
| `miner/oracle.go`, `miner/oracle.py` | Local helper and private pipe interface to the official Go VRF/keystore implementation |
| `miner/setup.py`, `miner/validate.py` | First-run correctness checks, nonce boundary tests, performance calibration, and device setup |
| `miner/device_config.py`, `miner/device_profile.py` | Device choice, PCI identity, validated device/driver/kernel fingerprint, and profile loading |
| `miner/telemetry.py` | Read-only AMD ADL/NVIDIA NVML telemetry matched to the selected GPU |
| `miner/power_control.py`, `miner/thermal_control.py` | Average board-power pacing and temperature protections |
| `miner/acceptance_totals.py`, `miner/status_io.py` | Local session/cumulative accounting and atomic status publication |
| `miner/wallet.py`, `miner/paths.py` | Independent recipient wallet setup and separate per-user data paths |
| `miner/diagnostics.py` | Allowlisted local diagnostic export with path/credential scrubbing |
| `assets/scripts/Backup-Wallet.ps1` | Local backup of the encrypted keystore and recovery instructions; excludes DPAPI unlock data |
| `assets/launch.json` | Public pinned network identity and node endpoints; contains no payout wallet |

`miner/tweetnacl.c` preserves the original public-domain source for the curve and SHA-512 primitives adapted into the kernel. Tests, documentation, and build scripts are part of the custom source release as well.

## Kernel changes in 0.1.1

The custom OpenCL kernel uses a 10-limb field representation, a scalar NAF representation shared within each workgroup, and a compact SHA-512 message buffer. The SHA-512 implementation retains the second padding block when the supported 69-byte prefix produces a 113-byte nonce-bearing input. These are implementation changes to the custom seeker; the official client and VRF rules remain pinned to the source below.

Device profiles include the kernel hash. Updating this kernel requires recipients to run **GPU and wallet setup** again for correctness checks and fresh performance/power calibration. Setup preserves an existing wallet, writes a new device profile, and selects Maximum; users should reselect their desired power mode. See [CHANGELOG.md](CHANGELOG.md) for the measured development-card comparison and its limitations.

## Official Proxima source

- Repository: <https://github.com/lunfardo314/proxima>
- Release: `v1.0.2-take1`
- Commit: `60515d0074e63e467de6d63532c1236c1bec332a`
- Commit time: `2026-10-18T14:04:58Z`
- Source directory: `upstream/`
- License: `upstream/LICENSE`, plus package-specific notices

The snapshot is preserved without a `.git` directory. Its module locks are kept intact. The portable build supplies the pinned version identity to archive builds; changing source or build inputs requires rebuilding and validating the result. The custom application invokes the official client; it does not replace Proxima's ledger rules.

## Toolchain and runtime provenance

| Component | Version/source | Distribution treatment |
| --- | --- | --- |
| Go | Go 1.26.6, Windows amd64; <https://go.dev/dl/> | Build prerequisite, not a bundled compiler. Runtime notices are retained in `assets/licenses/`. |
| Python | CPython 3.13.7 Windows amd64 embeddable package; <https://www.python.org/downloads/release/python-3137/> | Included in binary releases; excluded from Git. CPython binaries/stdlib are unmodified; `_pth` configuration adds application import paths. |
| Python dependencies | Standard library and `ctypes` | No additional pip packages are required by the application. |
| OpenCL | Installed AMD/NVIDIA graphics driver | Driver library is not distributed here. The kernel compiles for the selected device at runtime. |
| AMD ADL / NVIDIA NVML | Installed GPU driver | Read-only sensor interfaces; vendor binaries are not redistributed. |
| TweetNaCl | <https://tweetnacl.cr.yp.to/> | Original `miner/tweetnacl.c` retained; public-domain provenance is recorded. |

The Python license bundle also covers its supplied third-party components, including OpenSSL, libffi, SQLite, and Microsoft runtime redistribution terms. See `assets/licenses/Python-LICENSE.txt` and the embedded runtime's own license file. Sources for the unmodified Python runtime are available from the official Python release page; this repository does not claim to contain the entire CPython or Go toolchain source tree.

## Dependency and license records

`upstream/go.mod` and `upstream/go.sum` pin Go module versions and content checksums. Build tooling resolves those upstream dependencies; the repository does not duplicate every dependency source tree. `assets/licenses/dependencies.json` inventories exact modules linked in the supplied native helper binaries and records their notice paths. A new build records its own artifact hashes separately.

License text and attribution copies are under `assets/licenses/modules/`. The included unmodified MPL-covered sources are under `assets/licenses/source/`:

- `github.com/hashicorp/golang-lru` v1.0.2
- `github.com/libp2p/go-yamux/v5` v5.1.0

The FreeType-Go component uses the FreeType License option, with its acknowledgment and full terms preserved. The EasyFL module is pinned at `v0.0.0-20261012131332-8e4d838e7b0b`; no license file was present at that commit. The package owner confirmed redistribution authorization. This record does not invent grant text or treat EasyFL as covered by Proxima's MIT license.

See [LICENSE.txt](LICENSE.txt), [miner/LICENSE.txt](miner/LICENSE.txt), and [THIRD-PARTY-NOTICES.txt](assets/licenses/THIRD-PARTY-NOTICES.txt). Individual component terms remain applicable to their own files.

## Release boundaries

Generated executables, downloaded runtimes, caches, local build work, test output, keystores, passwords, device profiles, mining logs, and backups do not belong in Git. Runtime data stays outside the application folder by default. Distribution packaging must use an explicit source/artifact allowlist and verify hashes; copying an installed user's complete directory is not a release process.

Tests use synthetic fixtures. GPU protocol tests must use their own isolated temporary data and test credentials, never a user's wallet. Real GPU validation is separate from CPU regression tests and from live mining. No test result guarantees future network acceptance, rewards, or equal performance across devices.

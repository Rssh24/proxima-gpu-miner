# Proxima GPU Miner for Windows

A community GPU miner for the Proxima Take 1 network, with an English desktop interface and a custom OpenCL nonce seeker. This repository contains the application source and an unmodified snapshot of the official Proxima client.

**Windows beta 0.1.1.** Developed and tested on an AMD Radeon RX 9070 XT. Other AMD and NVIDIA cards are experimental; they must pass their own correctness, telemetry, and setup checks. This is not an official Proxima or GPU-vendor release.

## Download and start

1. Download the Windows binary ZIP and its SHA-256 file from [Releases](https://github.com/Rssh24/proxima-gpu-miner/releases). GitHub's automatic "Source code" downloads contain source, not a ready-to-run miner.
2. Extract the complete ZIP, then open `Proxima-Miner.exe` as your normal Windows user. Administrator rights should not be required. A vendor graphics driver with OpenCL support is required.
3. The app detects and selects a supported GPU automatically, preferring a discrete card. Click **GPU and wallet setup**. On a multi-GPU PC, **Change GPU** is an optional override; no AMD/NVIDIA choice is required.
4. Setup checks GPU results against the official VRF implementation, measures performance, and creates your own encrypted wallet. Back up the encrypted wallet and save its recovery password separately.
5. Select an available power mode, then click **Start GPU mining**. Setup does not start mining automatically.

Only one GPU is used, and CPU mining is disabled. Closing the window leaves mining running in the background; use **Stop mining** to stop it. No startup task or Windows service is installed.

## Features

- AMD/NVIDIA device detection and device-specific correctness checks.
- Maximum, 50%, and 25% average board-power modes when power telemetry supports them. Pacing is implemented in software; GPU voltage, clocks, fans, and driver limits are not changed.
- Temperature protection with visible status. Core temperature is required. Sustained high temperature reduces the power target when telemetry permits; emergency thresholds stop mining.
- Separate wallet per Windows user by default, local balance lookup, wallet backup, and diagnostic export.
- Session and cumulative counts of locally accepted solutions. These are **not** confirmed rewards or wallet balance.

See the included [runtime guide](assets/README.txt) for thermal thresholds, backup/recovery, power modes, and stopping behavior. Take 1 is experimental: network changes or resets can require an updated client and can affect balances. There is no guaranteed time to a reward.

## Updating from 0.1.0

Stop mining in the old app before switching versions. Back up the encrypted wallet and recovery password separately, extract the new ZIP into a separate folder, and keep your existing data directory (or the same `PROXIMA_MINER_DATA` override).

Run **GPU and wallet setup** again. The new kernel invalidates the old GPU profile; setup checks the new calculations and recalibrates performance and average board power while preserving an existing wallet. Recalibration is an explicit action, not automatic on launch. Setup selects Maximum, so choose your preferred power mode again before starting mining. Keeping the data directory also preserves local cumulative acceptance counts.

## Performance in 0.1.1

The OpenCL kernel uses 10-limb field arithmetic, shares the scalar NAF representation within each workgroup, and reduces SHA-512 scratch storage. It also handles the SHA-512 padding boundary for the longest supported nonce prefix (69 bytes).

On the development RX 9070 XT, a controlled 20-second comparison using the same key measured **1.96M → 3.72M VRF attempts/s**, with average board power **295.52W → 266.56W**. A separate 37-second live-mining sample averaged **3.52M attempts/s at 261.45W**. These are short samples from one card, not NVIDIA results or a promise of sustained performance, accepted solutions, or rewards. Your GPU, driver, temperature, work, and settings affect the result.

See [the changelog](CHANGELOG.md) for the release changes.

## Data and privacy

The release contains no wallet, seed, recovery password, developer payout address, personal logs, or device profile. Setup creates your wallet locally. Default data location:

```text
%LOCALAPPDATA%\ProximaGpuMinerBeta\take1
```

`PROXIMA_MINER_DATA` can override that location for an isolated installation. Keep the data folder when updating. Windows DPAPI unlock information is local to your Windows account; portable recovery requires the encrypted `proxima.key` file **and** its separately saved recovery password.

**Export diagnostics** creates a local archive; it does not upload it. Review it before sharing. Never include wallet files, recovery passwords, or personal data folders in an issue or source contribution.

## Source and development

- [Source map and provenance](SOURCE.md)
- [Build and test instructions](BUILDING.md)
- [Pinned official Proxima source](upstream/) and [source identity](UPSTREAM.json)
- [Third-party notices](assets/licenses/THIRD-PARTY-NOTICES.txt)

The official client is pinned to `v1.0.2-take1`, commit `60515d0074e63e467de6d63532c1236c1bec332a`. The repository includes all custom application, integration, kernel, and test source. Generated executables, the Python runtime, build caches, and personal runtime data are excluded from Git.

Hardware support is a beta capability, not a claim of equal performance across cards. When reporting results, include the GPU model, driver version, measured VRF attempts/s, average board power if available, temperatures, and a reviewed diagnostic export. A locally accepted solution alone does not prove a network-confirmed reward.

## Licenses

Original application and OpenCL integration code is MIT licensed; see [LICENSE.txt](LICENSE.txt). The pinned Proxima source retains its [MIT license](upstream/LICENSE) and package notices. TweetNaCl-derived primitives retain their public-domain provenance. Other components retain their own terms; see [the notice index](assets/licenses/THIRD-PARTY-NOTICES.txt).

The pinned EasyFL dependency has no license file in its repository snapshot. The package owner has confirmed that redistribution is authorized. This records that confirmation without inventing license text or applying Proxima's MIT license to EasyFL.

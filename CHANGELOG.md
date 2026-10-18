# Changelog

## 0.1.1 — 2026-10-19

- Optimize the OpenCL VRF kernel with 10-limb field arithmetic, a scalar NAF representation shared within each workgroup, and compact SHA-512 scratch storage.
- Handle SHA-512 two-block padding for the longest supported 69-byte nonce prefix.
- Require fresh recipient GPU setup after the kernel change. Setup rechecks correctness and recalibrates performance/power; existing wallets and local acceptance history remain in the data directory. Setup selects Maximum, so reselect your preferred power mode.
- Keep automatic AMD/NVIDIA device selection, per-user wallets, GPU-only mining, local diagnostics, and thermal protection. Other AMD/NVIDIA models remain experimental.

### Development-card measurements

RX 9070 XT, Windows 11; controlled 20-second comparison using the same key:

| Metric | Previous kernel | Optimized kernel |
| --- | ---: | ---: |
| VRF attempts/s | 1,962,266 | 3,715,434 |
| Average board power | 295.52W | 266.56W |

A separate 37-second live-mining sample averaged 3,520,015 VRF attempts/s at 261.45W. These short samples are from one RX 9070 XT. They are not NVIDIA measurements or guarantees of sustained speed, power, accepted solutions, or rewards. Results depend on hardware, driver, temperature, settings, and available work.

For upgrade instructions, see [README.md](README.md#updating-from-010). Keep the data directory and wallet backup; do not copy a personal installation into a redistribution package.

## 0.1.0

Initial Windows beta with an English GUI, automatic AMD/NVIDIA GPU selection, a custom OpenCL nonce seeker, per-user encrypted wallets, power modes, temperature protection, local acceptance counters, and reviewed diagnostic export. Includes the custom source and a pinned official Proxima `v1.0.2-take1` source snapshot.

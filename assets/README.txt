PROXIMA GPU MINER — WINDOWS BETA 0.1.1

Community software for the Proxima Take 1 network. This is a Windows beta,
not an official Proxima or GPU-vendor release.

GETTING STARTED

1. Extract the complete package to a normal folder. Do not run it inside a ZIP.
2. Open Proxima-Miner.exe as your normal Windows user. Administrator rights
   should not be needed. Install the current AMD or NVIDIA graphics driver
   from its vendor if the application cannot find an OpenCL GPU.
3. The application automatically detects supported AMD and NVIDIA GPUs and
   prefers a discrete card over integrated graphics. Check the detected GPU
   summary, then click "GPU and wallet setup". If you have multiple cards,
   "Change GPU" lets you choose a different one before setup.
   Setup checks GPU results against the official implementation and runs a
   short performance test. This may take a few minutes. Mining does not start
   automatically.
4. Setup creates a new, encrypted wallet for you if none exists. Existing
   wallets are preserved. Back up your wallet and save its recovery password
   separately before relying on this installation.
5. Choose a supported power mode and click "Start GPU mining".

The user interface is English. CPU mining is disabled. Only one selected GPU
is used. The RX 9070 XT is the tested development card; other AMD and NVIDIA
cards are experimental and must pass their own setup and correctness checks.
Performance varies by GPU, driver, temperature, workload, and network work.
Passing setup does not establish long-term stability or guarantee rewards.

UPDATING FROM 0.1.0

Stop mining in the old app before switching versions. Back up the encrypted
wallet and save the recovery password separately. Extract the complete new ZIP
into a separate application folder. Keep your existing personal data folder,
or the same PROXIMA_MINER_DATA override, to retain your wallet and local totals.

Click "GPU and wallet setup" again before mining. The optimized kernel changes
its fingerprint, so the old GPU profile cannot be reused. Setup checks the new
GPU calculations and recalibrates performance and average board power. It keeps
an existing wallet. This recalibration is not automatic on application launch.
Setup selects Maximum; reselect your preferred power mode before starting.

The development RX 9070 XT measured 1.96M to 3.72M VRF attempts/s in a controlled
20-second comparison using the same key. Average board power changed from
295.52W to 266.56W. A separate 37-second live sample averaged 3.52M attempts/s
at 261.45W. These short samples do not establish sustained results on other
cards or drivers, and higher attempt rates do not guarantee rewards.

WALLET AND RECOVERY

Your wallet is created on your own PC. This package contains no wallet,
private key, recovery password, developer payout address, or wallet backup.
The public wallet address is available in the application. Never share the
private key or recovery password in chat, screenshots, logs, or uploads.

Use the wallet-backup action to choose a local destination. It saves the
encrypted proxima.key file and recovery instructions. Save the wallet's
recovery password separately using the application's local password display.
An offline external drive is preferable to a backup on the same physical disk.
The encrypted key file plus the correct recovery password are needed to
recover on another PC or after reinstalling Windows.

The application keeps its automatic unlock information protected by Windows
DPAPI for your Windows user account. That unlock file is not a portable
recovery method and is intentionally excluded from the backup action.
Do not delete your local data folder when updating or replacing the program.

PERSONAL DATA AND LOGS

Default location:
  %LOCALAPPDATA%\ProximaGpuMinerBeta\take1

An explicit PROXIMA_MINER_DATA environment variable overrides this location
for isolated testing or an advanced custom installation. Different Windows
accounts and different PCs have separate data and wallets by default.
Application files stay separate from this personal data directory. Share only
a clean distribution package, never a copied personal data folder.

SHARING DIAGNOSTICS

Use "Export diagnostics" when reporting a problem. It creates a local ZIP of
recent allowlisted logs, GPU setup information, version details, and public
status. The export does not open wallet files and excludes recovery credentials.
It attempts to remove local paths and sensitive-looking text from logs.
Review the ZIP before you choose to share it: public node URLs and activity
times can remain. The application never uploads or sends this archive for you.
The archive is saved under the diagnostics subfolder of your personal data.

RUNNING AND STOPPING

Closing the control window leaves an already running miner in the background.
Open the application again to see its status or click "Stop mining" to stop it.
Closing the window is not a stop command. There is no scheduled time limit.
The program does not install a startup task, Windows service, or automatic
restart after a safety stop. Rebooting Windows stops the background processes.

The "Locally accepted" display has two counts. "This session" resets when
mining starts again. "Total" is saved in this PC's personal data folder and
continues across mining sessions. It does not include another PC's history.
Keep the data folder to preserve that local total when updating the program.

Both counts track locally accepted solutions, not PROX earned or your wallet
balance. A local accepted solution does not by itself mean a transaction was
confirmed or a reward reached the wallet. Use the balance action to check the
public account state. No fixed waiting time or income is guaranteed.

POWER MODES

Maximum: no software pacing; the card follows its current driver settings.
Balanced (50%): targets half the measured maximum average board power.
Eco (25%): targets one quarter of that average board-power reference.

These are software average-power targets, not driver power-limit percentages.
Short power peaks can exceed the target. The application does not change
voltage, GPU clocks, fan settings, or driver power limits. Close other GPU
workloads for a meaningful calibration. Stop mining before changing modes.
Some cards cannot reach a very low target because their idle power is higher.
If board-power telemetry is unavailable, only Maximum is supported.

AUTOMATIC THERMAL PROTECTION

Core temperature is mandatory. A core temperature of 80 C or more stops
mining immediately. If hotspot telemetry is available, 105 C or more also
stops mining immediately.

With hotspot telemetry: 95 C or more continuously for 60 seconds triggers
thermal protection. Without hotspot telemetry: core temperature of 75 C or
more continuously for 60 seconds triggers it instead. Dropping below the
applicable threshold before 60 seconds resets that timer.

If reliable board-power telemetry is available, thermal protection reduces
the average-power target to at most 95% of the calibrated maximum reference.
It never raises a lower target already selected. The restriction remains until
mining is restarted. The interface reports that protection is active.

Without reliable board-power telemetry, the application cannot enforce this
automatic power target; it stops mining when the continuous soft-temperature
condition is reached. Missing required safety telemetry can also stop mining.
After a stop, inspect the reason and cooling before starting again.

NETWORK AND CONNECTIONS

The miner connects to configured public Proxima endpoints. Its local external
seeker interface remains bound to loopback. No router forwarding, remote
desktop setup, or firewall opening is needed by this package.
The official client and pinned network identity must match the current network.
Take 1 is experimental and may be stopped or reset; tokens and rewards are not
promised to retain value or survive a network reset.

LICENSES AND REDISTRIBUTION STATUS

See licenses/THIRD-PARTY-NOTICES.txt and licenses/dependencies.json. Required
notices are retained, and the included MPL-covered dependency sources are
under licenses/source/.

EasyFL has no license file at the pinned commit. The package owner has confirmed
that redistribution is authorized. This records that permission confirmation;
it does not invent a license text or assign Proxima's MIT license to EasyFL.
No public upload is performed by this program.

This software is provided under its included license terms without warranties.

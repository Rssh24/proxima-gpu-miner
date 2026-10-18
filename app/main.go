// Proxima Take 1: local Windows control panel. No wallet secrets are logged.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

var (
	user                              = syscall.NewLazyDLL("user32.dll")
	kernel                            = syscall.NewLazyDLL("kernel32.dll")
	gdi                               = syscall.NewLazyDLL("gdi32.dll")
	shell                             = syscall.NewLazyDLL("shell32.dll")
	crypt                             = syscall.NewLazyDLL("crypt32.dll")
	createWindow                      = user.NewProc("CreateWindowExW")
	send                              = user.NewProc("SendMessageW")
	setText                           = user.NewProc("SetWindowTextW")
	defWindow                         = user.NewProc("DefWindowProcW")
	root                              string
	dataRoot                          string
	devices                           []publicDevice
	deviceListing                     bool
	deviceOverride                    bool
	recommendedDeviceKey              string
	setupRunning                      bool
	diagnosticsRunning                bool
	diagnosticsEvents                 = make(chan bool, 1)
	setupLaunch                       supervisor
	setupInfo                         setupStatus
	profile                           deviceProfile
	deviceEvents                      = make(chan deviceEvent, 1)
	setupEvents                       = make(chan bool, 1)
	hwnd                              uintptr
	normalFont, titleFont, statusFont uintptr
	controls                          = map[int]uintptr{}
	current                           supervisor
	launch                            supervisor
	samples                           []sample
	previousPID                       int
	statusHint                        string
	starting                          bool
	selectedMode                      = "maximum"
	modeNeedsChoice                   bool
	rewardText                              = "Rewards: check the miner log; accepted solutions are separate."
	logOffset                         int64 = -1
	lastLogCheck                      time.Time
)

const (
	wmCreate          = 0x0001
	wmDestroy         = 0x0002
	wmClose           = 0x0010
	wmCommand         = 0x0111
	wmTimer           = 0x0113
	wmSetFont         = 0x0030
	startID           = 101
	stopID            = 102
	logsID            = 103
	guideID           = 104
	addressID         = 105
	passwordID        = 106
	backupID          = 107
	balanceID         = 108
	maxModeID         = 109
	balancedModeID    = 110
	ecoModeID         = 111
	deviceComboID     = 112
	setupID           = 113
	setupStatusID     = 206
	wmDevices         = 0x8001
	wmSetupDone       = 0x8002
	wmDiagnosticsDone = 0x8003
	diagnosticsID     = 114
	chooseDeviceID    = 115
	deviceSummaryID   = 207
	statusID          = 201
	hashID            = 202
	countersID        = 203
	sensorID          = 204
	rewardID          = 205
)

type point struct{ X, Y int32 }
type rect struct{ Left, Top, Right, Bottom int32 }
type msg struct {
	Window  uintptr
	Message uint32
	WParam  uintptr
	LParam  uintptr
	Time    uint32
	Point   point
	Private uint32
}
type windowClass struct {
	Size        uint32
	Style       uint32
	WndProc     uintptr
	ClassExtra  int32
	WindowExtra int32
	Instance    uintptr
	Icon        uintptr
	Cursor      uintptr
	Background  uintptr
	MenuName    *uint16
	ClassName   *uint16
	SmallIcon   uintptr
}
type supervisor struct {
	PID            int     `json:"pid"`
	Started        float64 `json:"started_unix"`
	ProcessStarted float64 `json:"process_started_unix"`
	Network        string  `json:"network"`
	CPUWorkers     int     `json:"cpu_workers"`
}

func (s supervisor) birth() float64 {
	if s.ProcessStarted > 0 {
		return s.ProcessStarted
	}
	return s.Started
}

type gpuStatus struct {
	Time                 float64  `json:"time"`
	Attempts             uint64   `json:"total_attempts"`
	Jobs                 uint64   `json:"jobs_received"`
	Solutions            uint64   `json:"solutions_accepted"`
	CumulativeSolutions  *uint64  `json:"cumulative_solutions_accepted"`
	CumulativePersisted  *bool    `json:"cumulative_totals_persisted"`
	Stale                uint64   `json:"stale_results"`
	Elapsed              float64  `json:"elapsed_seconds"`
	Busy                 *float64 `json:"gpu_busy_percent"`
	Power                *float64 `json:"board_power_w"`
	Edge                 *float64 `json:"edge_c"`
	Hotspot              *float64 `json:"hotspot_c"`
	Memory               *float64 `json:"memory_c"`
	PowerTarget          *float64 `json:"power_target_w"`
	PowerAverage         *float64 `json:"power_average_w"`
	PowerUnreachable     bool     `json:"power_target_unreachable"`
	PowerDispatchPaused  bool     `json:"power_dispatch_paused"`
	PowerStatus          string   `json:"power_status"`
	PerformanceMode      string   `json:"performance_mode"`
	ThermalLimited       bool     `json:"thermal_limited"`
	ThermalHotSeconds    float64  `json:"thermal_hot_seconds"`
	ThermalPowerFraction *float64 `json:"thermal_power_fraction"`
}
type sample struct {
	at    float64
	count uint64
}
type dataBlob struct {
	Size uint32
	Data *byte
}

func u(s string) *uint16 { p, _ := syscall.UTF16PtrFromString(s); return p }
func message(text, title string, flags uintptr) uintptr {
	r, _, _ := user.NewProc("MessageBoxW").Call(hwnd, uintptr(unsafe.Pointer(u(text))), uintptr(unsafe.Pointer(u(title))), flags)
	return r
}
func text(id int, value string) { setText.Call(controls[id], uintptr(unsafe.Pointer(u(value)))) }
func enabled(id int, yes bool) {
	v := uintptr(0)
	if yes {
		v = 1
	}
	user.NewProc("EnableWindow").Call(controls[id], v)
}
func addControl(class, caption string, id, x, y, w, h int, style uintptr, font uintptr) {
	hctl, _, _ := createWindow.Call(0, uintptr(unsafe.Pointer(u(class))), uintptr(unsafe.Pointer(u(caption))), 0x50000000|style, uintptr(x), uintptr(y), uintptr(w), uintptr(h), hwnd, uintptr(id), 0, 0)
	controls[id] = hctl
	send.Call(hctl, wmSetFont, font, 1)
}
func makeFont(height, weight int) uintptr {
	h, _, _ := gdi.NewProc("CreateFontW").Call(uintptr(int32(-height)), 0, 0, 0, uintptr(weight), 0, 0, 0, 1, 0, 0, 5, 0, uintptr(unsafe.Pointer(u("Segoe UI"))))
	return h
}
func createControls() {
	normalFont = makeFont(17, 400)
	titleFont = makeFont(27, 700)
	statusFont = makeFont(20, 600)
	addControl("STATIC", "Proxima GPU Miner - Windows Beta", 301, 24, 18, 772, 36, 0, titleFont)
	addControl("STATIC", "Take 1 | AMD / NVIDIA OpenCL | GPU mining only", 302, 24, 61, 772, 27, 0, normalFont)
	addControl("STATIC", "GPU detected automatically", 306, 24, 99, 510, 23, 0, normalFont)
	addControl("BUTTON", "Change GPU", chooseDeviceID, 640, 91, 154, 30, 0x00010000, normalFont)
	addControl("STATIC", "Detecting a supported GPU...", deviceSummaryID, 24, 126, 510, 30, 0, normalFont)
	addControl("COMBOBOX", "", deviceComboID, 24, 126, 510, 240, 0x00210003, normalFont)
	send.Call(controls[deviceComboID], 0x0160, 770, 0)
	addControl("BUTTON", "GPU and wallet setup", setupID, 548, 123, 246, 36, 0x00010000, normalFont)
	addControl("STATIC", "Looking for supported GPUs...", setupStatusID, 24, 173, 772, 42, 0, normalFont)
	addControl("STATIC", "Stopped - run setup before mining", statusID, 24, 229, 772, 45, 0, statusFont)
	addControl("STATIC", "GPU attempts/s (last 10 seconds): -", hashID, 24, 287, 772, 29, 0, statusFont)
	addControl("STATIC", acceptanceCounters(nil), countersID, 24, 331, 772, 51, 0, normalFont)
	addControl("STATIC", "GPU utilization: -    Board power: -\r\nCore: -    Hotspot: -    Memory: -", sensorID, 24, 394, 772, 51, 0, normalFont)
	addControl("STATIC", rewardText, rewardID, 24, 458, 772, 27, 0, normalFont)
	addControl("STATIC", "Auto temperature protection; limits depend on available sensors.\r\nLocally accepted solutions are separate from confirmed ledger rewards.", 303, 24, 496, 772, 43, 0, normalFont)
	addControl("BUTTON", "Start GPU mining", startID, 24, 553, 190, 40, 0x00010001, normalFont)
	addControl("BUTTON", "Stop mining", stopID, 226, 553, 150, 40, 0x00010000, normalFont)
	addControl("BUTTON", "Open logs", logsID, 388, 553, 180, 40, 0x00010000, normalFont)
	addControl("BUTTON", "Read me", guideID, 580, 553, 214, 40, 0x00010000, normalFont)
	addControl("BUTTON", "Wallet address / copy", addressID, 24, 610, 250, 40, 0x00010000, normalFont)
	addControl("BUTTON", "Show passphrase", passwordID, 286, 610, 220, 40, 0x00010000, normalFont)
	addControl("BUTTON", "Back up encrypted wallet", backupID, 518, 610, 276, 40, 0x00010000, normalFont)
	addControl("BUTTON", "Check wallet balance", balanceID, 24, 666, 250, 40, 0x00010000, normalFont)
	addControl("BUTTON", "Export diagnostics", diagnosticsID, 286, 666, 220, 40, 0x00010000, normalFont)
	addControl("STATIC", "Background mining is optional.\r\nRestart manually after reboot.", 304, 518, 666, 276, 45, 0, normalFont)
	addControl("BUTTON", "Maximum", maxModeID, 24, 728, 210, 30, 0x00030009, normalFont)
	addControl("BUTTON", "Balanced (50%)", balancedModeID, 286, 728, 240, 30, 0x00010009, normalFont)
	addControl("BUTTON", "Eco (25%)", ecoModeID, 548, 728, 246, 30, 0x00010009, normalFont)
	addControl("STATIC", "Average board-power targets; short peaks are allowed.\r\nPower target modes require a supported board-power sensor.", 305, 24, 771, 772, 43, 0, normalFont)
	readDataState()
	loadMode()
	showDeviceChoice()
	enabled(stopID, false)
	user.NewProc("SetTimer").Call(hwnd, 1, 1000, 0)
	deviceListing = true
	refresh()
	enumerateDevices()
}

type publicDevice struct {
	Key          string `json:"device_key"`
	Name         string `json:"name"`
	Vendor       string `json:"vendor"`
	Memory       uint64 `json:"global_memory_bytes"`
	ComputeUnits uint64 `json:"compute_units"`
	HostUnified  *bool  `json:"host_unified_memory"`
}
type deviceProfile struct {
	Key            string `json:"device_key"`
	Name           string `json:"device_name"`
	PowerAvailable bool   `json:"power_available"`
	Modes          map[string]struct {
		Enabled bool   `json:"enabled"`
		Reason  string `json:"reason"`
	} `json:"modes"`
}
type setupStatus struct {
	State      string `json:"state"`
	Message    string `json:"message"`
	DeviceName string `json:"device_name"`
}
type deviceEvent struct {
	Devices     []publicDevice
	Recommended string
	Error       string
}

func resolveDataRoot() (string, error) {
	if v := strings.TrimSpace(os.Getenv("PROXIMA_MINER_DATA")); v != "" {
		return filepath.Abs(v)
	}
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		return "", fmt.Errorf("LOCALAPPDATA is unavailable")
	}
	return filepath.Abs(filepath.Join(local, "ProximaGpuMinerBeta", "take1"))
}
func ensureDataDirectories() error {
	for _, p := range []string{dataRoot, filepath.Join(dataRoot, "wallet"), filepath.Join(dataRoot, "logs"), filepath.Join(dataRoot, "work"), filepath.Join(dataRoot, "work", "ocl-cache")} {
		if err := os.MkdirAll(p, 0700); err != nil {
			return err
		}
	}
	return nil
}
func childEnvironment() []string {
	env := []string{}
	for _, v := range os.Environ() {
		name, _, _ := strings.Cut(v, "=")
		if strings.EqualFold(name, "PROXIMA_KEY_PASSPHRASE") || strings.EqualFold(name, "NONCE_SEEKER_SEED") {
			continue
		}
		env = append(env, v)
	}
	return append(env, "PROXIMA_MINER_DATA="+dataRoot, "PYTHONUTF8=1", "PYTHONDONTWRITEBYTECODE=1", "AMD_OCL_CACHE_ENABLE=0", "AMD_OCL_CACHE_PATH="+filepath.Join(dataRoot, "work", "ocl-cache"), "TEMP="+filepath.Join(dataRoot, "work"), "TMP="+filepath.Join(dataRoot, "work"))
}
func setupCommand(key string) *exec.Cmd {
	cmd := exec.Command(filepath.Join(root, "tools", "python", "python.exe"), "-X", "utf8", "-u", filepath.Join(root, "miner", "setup.py"), "--device", key)
	cmd.Dir = root
	cmd.Env = childEnvironment()
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	return cmd
}
func enumerateDevices() {
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, filepath.Join(root, "tools", "python", "python.exe"), "-X", "utf8", "-u", filepath.Join(root, "miner", "setup.py"), "--list-devices")
		cmd.Dir = root
		cmd.Env = childEnvironment()
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
		cmd.Stderr = io.Discard
		out, err := cmd.Output()
		var inventory struct {
			Devices     []publicDevice `json:"devices"`
			Recommended string         `json:"recommended_device_key"`
		}
		event := deviceEvent{}
		if err != nil || json.Unmarshal(out, &inventory) != nil {
			event.Error = "Could not list GPUs. Check the graphics driver and the readme."
		} else {
			event.Recommended = inventory.Recommended
			for _, device := range inventory.Devices {
				if device.Key != "" && device.Name != "" {
					event.Devices = append(event.Devices, device)
				}
			}
			if len(event.Devices) == 0 {
				event.Error = "No supported AMD or NVIDIA OpenCL GPU was found."
			}
		}
		deviceEvents <- event
		user.NewProc("PostMessageW").Call(hwnd, wmDevices, 0, 0)
	}()
}
func selectedDeviceKey() string {
	if len(devices) == 0 {
		return ""
	}
	index, _, _ := send.Call(controls[deviceComboID], 0x0147, 0, 0)
	if index >= uintptr(len(devices)) {
		return ""
	}
	return devices[index].Key
}

func preferredDeviceIndex(inventory []publicDevice, savedKey string, recommendation ...string) int {
	if len(inventory) == 0 {
		return -1
	}
	// A previously configured choice always wins. Otherwise use the backend's
	// vendor-aware recommendation, then a deterministic non-benchmark fallback.
	for index, device := range inventory {
		if savedKey != "" && device.Key == savedKey {
			return index
		}
	}
	if len(recommendation) > 0 && recommendation[0] != "" {
		for index, device := range inventory {
			if device.Key == recommendation[0] {
				return index
			}
		}
	}
	rank := func(device publicDevice) int {
		if device.HostUnified == nil {
			return 1
		}
		if *device.HostUnified {
			return 2
		}
		return 0
	}
	best := 0
	for index, device := range inventory {
		previous := inventory[best]
		if rank(device) < rank(previous) || (rank(device) == rank(previous) && (device.ComputeUnits > previous.ComputeUnits || (device.ComputeUnits == previous.ComputeUnits && (device.Memory > previous.Memory || (device.Memory == previous.Memory && device.Key < previous.Key))))) {
			best = index
		}
	}
	return best
}
func showDeviceChoice() {
	show := func(id int, yes bool) {
		flag := uintptr(0)
		if yes {
			flag = 5
		}
		user.NewProc("ShowWindow").Call(controls[id], flag)
	}
	show(deviceComboID, deviceOverride)
	show(deviceSummaryID, !deviceOverride)
	show(chooseDeviceID, len(devices) > 1)
	if deviceOverride {
		text(306, "Optional GPU override")
		text(chooseDeviceID, "Use auto GPU")
	} else {
		text(306, "GPU detected automatically")
		text(chooseDeviceID, "Change GPU")
	}
}
func toggleDeviceChoice() {
	if !controlsAvailable(currentSupervisor().PID > 0) || len(devices) < 2 {
		return
	}
	deviceOverride = !deviceOverride
	if !deviceOverride {
		index := preferredDeviceIndex(devices, "", recommendedDeviceKey)
		if index >= 0 {
			send.Call(controls[deviceComboID], 0x014e, uintptr(index), 0)
		}
	}
	clearUnsupportedSelection()
	showDeviceChoice()
	refresh()
}
func regularFileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
func walletAvailability() (publicAndKey, unlock bool) {
	publicAndKey = regularFileExists(filepath.Join(dataRoot, "wallet", "public.json")) && regularFileExists(filepath.Join(dataRoot, "wallet", "proxima.key"))
	unlock = publicAndKey && regularFileExists(filepath.Join(dataRoot, "wallet", "unlock.dpapi"))
	return
}
func readyForDevice() bool {
	ready, _ := readyForMining(selectedDeviceKey())
	return ready
}
func updateWalletControls() {
	available, unlock := walletAvailability()
	enabled(addressID, available && !setupRunning)
	enabled(balanceID, available && !setupRunning)
	enabled(passwordID, unlock && !setupRunning)
	enabled(backupID, unlock && !setupRunning)
}
func stoppedStatusText(ready bool, hint string) string {
	if !ready {
		return "Stopped - run GPU setup first"
	}
	if hint != "" {
		return hint
	}
	return "Stopped - click Start GPU mining"
}

func finishDeviceList() {
	select {
	case event := <-deviceEvents:
		deviceListing = false
		devices = event.Devices
		recommendedDeviceKey = event.Recommended
		deviceOverride = false
		send.Call(controls[deviceComboID], 0x014b, 0, 0)
		selected := preferredDeviceIndex(devices, profile.Key, recommendedDeviceKey)
		for _, d := range devices {
			label := d.Name
			if d.Memory > 0 {
				label += fmt.Sprintf(" (%.1f GiB)", float64(d.Memory)/(1<<30))
			}
			send.Call(controls[deviceComboID], 0x0143, 0, uintptr(unsafe.Pointer(u(label))))
		}
		if len(devices) > 0 {
			send.Call(controls[deviceComboID], 0x014e, uintptr(selected), 0)
		}
		if event.Error != "" {
			statusHint = event.Error
		}
		clearUnsupportedSelection()
		showDeviceChoice()
		refresh()
	default:
	}
}
func readDataState() {
	var p deviceProfile
	if b, e := os.ReadFile(filepath.Join(dataRoot, "device-profile.json")); e == nil {
		_ = json.Unmarshal(b, &p)
	}
	profile = p
	var status setupStatus
	if b, e := os.ReadFile(filepath.Join(dataRoot, "setup-status.json")); e == nil {
		_ = json.Unmarshal(b, &status)
	}
	setupInfo = status
}
func modeAvailable(mode string) bool {
	if mode == "maximum" {
		return true
	}
	if !profile.PowerAvailable {
		return false
	}
	if capability, ok := profile.Modes[mode]; ok {
		return capability.Enabled
	}
	return mode == "balanced" || mode == "eco"
}
func clearUnsupportedSelection() {
	if !deviceListing && !setupRunning && validMode(selectedMode) && !modeAvailable(selectedMode) {
		selectedMode = ""
		modeNeedsChoice = true
		setModeChecks("")
		statusHint = "That power mode is unsupported on this GPU. Choose Maximum."
	}
}
func readyForMining(key string) (bool, string) {
	if key == "" {
		return false, "Wait for automatic GPU detection, then click GPU and wallet setup."
	}
	if setupInfo.State != "ready" || profile.Key != key || profile.Name == "" {
		return false, "Complete GPU and wallet setup for the selected device before mining."
	}
	if available, unlock := walletAvailability(); !available || !unlock {
		return false, "Wallet setup is incomplete. Run GPU and wallet setup."
	}
	var public struct {
		Holder string `json:"holder_id"`
	}
	b, e := os.ReadFile(filepath.Join(dataRoot, "wallet", "public.json"))
	if e != nil || json.Unmarshal(b, &public) != nil || len(public.Holder) != 64 {
		return false, "Wallet setup is incomplete. Run GPU and wallet setup."
	}
	for _, c := range public.Holder {
		if !strings.ContainsRune("0123456789abcdefABCDEF", c) {
			return false, "The public wallet address is invalid. Run setup again."
		}
	}
	return true, ""
}
func controlsAvailable(running bool) bool {
	return !running && !starting && !setupRunning && !deviceListing
}
func startSetup() {
	if !controlsAvailable(currentSupervisor().PID > 0) {
		return
	}
	key := selectedDeviceKey()
	if key == "" {
		message("No supported GPU was detected. Check the graphics driver and readme.", "GPU setup", 0x30)
		return
	}
	if err := ensureDataDirectories(); err != nil {
		message("Cannot create the local data folder.", "GPU setup", 0x10)
		return
	}
	log, e := os.OpenFile(filepath.Join(dataRoot, "logs", "setup.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if e != nil {
		message("Cannot open the setup log.", "GPU setup", 0x10)
		return
	}
	cmd := setupCommand(key)
	cmd.Stdout = log
	cmd.Stderr = log
	started := float64(time.Now().UnixNano()) / 1e9
	if e = cmd.Start(); e != nil {
		log.Close()
		message("Could not start setup. Open the logs folder.", "GPU setup", 0x10)
		return
	}
	setupRunning = true
	setupLaunch = supervisor{PID: cmd.Process.Pid, Started: started, ProcessStarted: started}
	statusHint = "Setup is running. Correctness checks and a short benchmark may take a few minutes."
	go func() {
		err := cmd.Wait()
		log.Close()
		setupEvents <- err == nil
		user.NewProc("PostMessageW").Call(hwnd, wmSetupDone, 0, 0)
	}()
	refresh()
}
func finishSetup() {
	select {
	case success := <-setupEvents:
		setupRunning = false
		setupLaunch = supervisor{}
		readDataState()
		loadMode()
		clearUnsupportedSelection()
		if success && setupInfo.State == "ready" {
			statusHint = "Setup complete. Back up the wallet, then click Start GPU mining."
		} else {
			statusHint = "Setup failed. Open logs for details; mining has not started."
		}
		refresh()
	default:
	}
}
func refreshSetup(running bool) {
	available := controlsAvailable(running)
	enabled(deviceComboID, available && len(devices) > 0)
	enabled(chooseDeviceID, available && len(devices) > 1)
	enabled(setupID, available && selectedDeviceKey() != "")
	summary := "GPU detected automatically. Click GPU and wallet setup. Existing wallets are preserved."
	if deviceListing {
		summary = "Looking for supported GPUs..."
	} else if len(devices) == 0 {
		summary = "No supported GPU detected. Check the graphics driver and readme."
	} else if setupRunning {
		summary = "Setup running: " + setupInfo.Message
	} else if setupInfo.State == "failed" {
		summary = "Setup failed: " + setupInfo.Message
	} else if profile.Key == selectedDeviceKey() && setupInfo.State == "ready" {
		summary = "Ready: " + profile.Name
	}
	if len(summary) > 220 {
		summary = summary[:220]
	}
	text(setupStatusID, summary)
	if key := selectedDeviceKey(); key != "" {
		for _, d := range devices {
			if d.Key == key {
				text(302, "Take 1 | "+d.Name+" | GPU only")
				text(deviceSummaryID, d.Name)
				break
			}
		}
	}
	if len(devices) == 0 {
		if deviceListing {
			text(deviceSummaryID, "Detecting a supported GPU...")
		} else {
			text(deviceSummaryID, "No supported GPU detected")
		}
	}
	if modeAvailable("balanced") || modeAvailable("eco") {
		text(305, "Average board-power targets relative to Maximum; short peaks are allowed.")
	} else {
		text(305, "50% and 25% modes need a supported board-power sensor.\r\nMaximum mode remains available; unavailable readings are shown as '-'.")
	}
}

// Only the bundled Python executable, with an independently verified birth time,
// can be treated as the supervisor or terminated. This rejects reused PIDs.
func openVerified(s supervisor, terminate bool) (uintptr, bool) {
	if s.PID <= 0 || s.birth() <= 0 {
		return 0, false
	}
	access := uintptr(0x1000)
	if terminate {
		access |= 1
	}
	h, _, _ := kernel.NewProc("OpenProcess").Call(access, 0, uintptr(s.PID))
	if h == 0 {
		return 0, false
	}
	closeBad := func() (uintptr, bool) { kernel.NewProc("CloseHandle").Call(h); return 0, false }
	var code uint32
	r, _, _ := kernel.NewProc("GetExitCodeProcess").Call(h, uintptr(unsafe.Pointer(&code)))
	if r == 0 || code != 259 {
		return closeBad()
	}
	buf := make([]uint16, 32768)
	n := uint32(len(buf))
	r, _, _ = kernel.NewProc("QueryFullProcessImageNameW").Call(h, 0, uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&n)))
	if r == 0 || !strings.EqualFold(filepath.Clean(syscall.UTF16ToString(buf[:n])), filepath.Join(root, "tools", "python", "python.exe")) {
		return closeBad()
	}
	var created, exited, kernelTime, userTime syscall.Filetime
	r, _, _ = kernel.NewProc("GetProcessTimes").Call(h, uintptr(unsafe.Pointer(&created)), uintptr(unsafe.Pointer(&exited)), uintptr(unsafe.Pointer(&kernelTime)), uintptr(unsafe.Pointer(&userTime)))
	birth := float64(int64(uint64(created.HighDateTime)<<32|uint64(created.LowDateTime))-116444736000000000) / 1e7
	if r == 0 || math.Abs(birth-s.birth()) > 5 {
		return closeBad()
	}
	return h, true
}
func alive(s supervisor) bool {
	h, ok := openVerified(s, false)
	if ok {
		kernel.NewProc("CloseHandle").Call(h)
	}
	return ok
}
func currentSupervisor() supervisor {
	var s supervisor
	b, e := os.ReadFile(filepath.Join(dataRoot, "logs", "supervisor.json"))
	if e == nil && json.Unmarshal(b, &s) == nil && s.Network == "take1" && s.CPUWorkers == 0 && alive(s) {
		return s
	}
	if alive(launch) {
		return launch
	}
	return supervisor{}
}

// Profiles select a locally calibrated pacing policy. These controls never
// modify GPU driver settings, clocks, voltage, or hardware power limits.
type performanceProfile struct {
	Mode         string `json:"mode"`
	LegacyTarget *int64 `json:"target_attempts_per_second,omitempty"`
}

func validMode(mode string) bool {
	return mode == "maximum" || mode == "balanced" || mode == "eco"
}
func decodeMode(data []byte) (string, error) {
	var profile performanceProfile
	if err := json.Unmarshal([]byte(strings.TrimPrefix(string(data), "\ufeff")), &profile); err != nil {
		return "", err
	}
	if validMode(profile.Mode) {
		return profile.Mode, nil
	}
	if profile.Mode == "" && profile.LegacyTarget != nil {
		switch *profile.LegacyTarget {
		case 0:
			return "maximum", nil
		case 800000:
			return "eco", nil
		}
	}
	return "", fmt.Errorf("unsupported mining mode")
}
func loadMode() {
	selectedMode = "maximum"
	modeNeedsChoice = false
	b, err := os.ReadFile(filepath.Join(dataRoot, "performance.json"))
	if os.IsNotExist(err) {
		setModeChecks(selectedMode)
		return // No profile defaults to maximum speed.
	}
	mode := ""
	if err == nil {
		mode, err = decodeMode(b)
	}
	if err != nil {
		selectedMode = ""
		modeNeedsChoice = true
		statusHint = "Cannot read the mode setting. Select a mode again."
		setModeChecks("")
		return
	}
	selectedMode = mode
	setModeChecks(mode)
}
func setModeChecks(mode string) {
	for _, item := range []struct {
		id   int
		mode string
	}{{maxModeID, "maximum"}, {balancedModeID, "balanced"}, {ecoModeID, "eco"}} {
		state := uintptr(0)
		if item.mode == mode {
			state = 1
		}
		send.Call(controls[item.id], 0x00f1, state, 0) // BM_SETCHECK
	}
}
func enableModeControls(yes bool) {
	enabled(maxModeID, yes)
	enabled(balancedModeID, yes && modeAvailable("balanced"))
	enabled(ecoModeID, yes && modeAvailable("eco"))
}
func saveMode(mode string) error {
	if !validMode(mode) {
		return fmt.Errorf("unsupported mining mode")
	}
	data, err := json.Marshal(performanceProfile{Mode: mode})
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(dataRoot, ".performance-*.tmp")
	if err != nil {
		return err
	}
	temporary := f.Name()
	defer os.Remove(temporary)
	if _, err = f.Write(append(data, '\n')); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	// Same-directory replacement is atomic; WRITE_THROUGH commits the rename.
	result, _, moveErr := kernel.NewProc("MoveFileExW").Call(uintptr(unsafe.Pointer(u(temporary))), uintptr(unsafe.Pointer(u(filepath.Join(dataRoot, "performance.json")))), 0x00000009)
	if result == 0 {
		return moveErr
	}
	return nil
}
func saveModeForStart() error {
	if modeNeedsChoice || !validMode(selectedMode) || !modeAvailable(selectedMode) {
		return fmt.Errorf("a valid mining mode must be selected")
	}
	return saveMode(selectedMode)
}
func chooseMode(mode string) {
	if starting || setupRunning || deviceListing || currentSupervisor().PID > 0 {
		setModeChecks(selectedMode)
		refresh()
		return
	}
	if !modeAvailable(mode) {
		setModeChecks(selectedMode)
		message("This GPU does not provide the board-power telemetry needed for that mode.", "Unsupported power mode", 0x30)
		return
	}
	if err := saveMode(mode); err != nil {
		setModeChecks(selectedMode)
		message("Cannot save the mode setting. Check access to the local data folder.", "Could not save setting", 0x10)
		return
	}
	selectedMode = mode
	modeNeedsChoice = false
	statusHint = "Mode saved. It applies at the next mining start."
	refresh()
}
func startMining() {
	if starting || setupRunning || deviceListing || currentSupervisor().PID > 0 {
		return
	}
	readDataState()
	if ok, why := readyForMining(selectedDeviceKey()); !ok {
		message(why, "Setup required", 0x30)
		return
	}
	starting = true
	enabled(startID, false)
	enableModeControls(false)
	defer func() { starting = false; refresh() }()
	if err := saveModeForStart(); err != nil {
		message("Could not validate or save the mode; mining has not started.\r\nSelect a supported mode and check access to the local data folder.", "Cannot start", 0x10)
		return
	}
	py := filepath.Join(root, "tools", "python", "python.exe")
	runner := filepath.Join(root, "miner", "run_mining.py")
	for _, p := range []string{py, runner, filepath.Join(root, "launch.json")} {
		if _, e := os.Stat(p); e != nil {
			message("A required program or configuration is missing. Read the readme.", "Cannot start", 0x10)
			return
		}
	}
	os.MkdirAll(filepath.Join(dataRoot, "logs"), 0700)
	out, e := os.OpenFile(filepath.Join(dataRoot, "logs", "supervisor.out.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if e != nil {
		message("Cannot open the supervisor output log.", "Cannot start", 0x10)
		return
	}
	defer out.Close()
	errlog, e := os.OpenFile(filepath.Join(dataRoot, "logs", "supervisor.err.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if e != nil {
		message("Cannot open the supervisor error log.", "Cannot start", 0x10)
		return
	}
	defer errlog.Close()
	cmd := exec.Command(py, "-X", "utf8", "-u", runner, "--network", "take1", "--allow-reward-delegation", "--max-seconds", "0")
	cmd.Dir = root
	cmd.Stdout = out
	cmd.Stderr = errlog
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	cmd.Env = childEnvironment()
	started := float64(time.Now().UnixNano()) / 1e9
	if e = cmd.Start(); e != nil {
		message("Could not start the miner. Open logs and read the readme.", "Cannot start", 0x10)
		return
	}
	launch = supervisor{PID: cmd.Process.Pid, Started: started, ProcessStarted: started, Network: "take1"}
	// Wait in the background so the supervisor survives closing this window.
	go func() { _ = cmd.Wait() }()
	statusHint = "Miner stopped or startup was blocked. Open logs for details."
	logOffset = -1
	rewardText = "Rewards: check the miner log; accepted solutions are separate."
	refresh()
}
func stopMining() bool {
	s := currentSupervisor()
	if s.PID == 0 {
		return true
	}
	h, ok := openVerified(s, true)
	if !ok {
		message("Cannot verify the miner process identity, so it was not stopped. Open logs.", "Process safety check", 0x30)
		return false
	}
	r, _, _ := kernel.NewProc("TerminateProcess").Call(h, 0)
	kernel.NewProc("CloseHandle").Call(h)
	if r == 0 {
		message("Could not stop the verified mining supervisor.", "Stop failed", 0x10)
		return false
	}
	statusHint = "Mining stopped"
	launch = supervisor{}
	samples = nil
	refresh()
	return true
}
func pretty(n uint64) string {
	s := strconv.FormatUint(n, 10)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}
func sensor(v *float64, unit string) string {
	if v == nil {
		return "—"
	}
	return fmt.Sprintf("%.0f%s", *v, unit)
}
func readGPU(s supervisor) (gpuStatus, bool) {
	var g gpuStatus
	b, e := os.ReadFile(filepath.Join(dataRoot, "logs", "gpu-status.json"))
	if e != nil || json.Unmarshal(b, &g) != nil {
		return g, false
	}
	now := float64(time.Now().UnixNano()) / 1e9
	return g, g.Time >= s.birth()-1 && now-g.Time >= -5 && now-g.Time <= 8
}
func updateRewards() {
	if time.Since(lastLogCheck) < 4*time.Second {
		return
	}
	lastLogCheck = time.Now()
	p := filepath.Join(dataRoot, "logs", "live-proxi.log")
	f, e := os.Open(p)
	if e != nil {
		return
	}
	defer f.Close()
	fi, e := f.Stat()
	if e != nil {
		return
	}
	// Start at the current end: a prior run's confirmations are never shown as
	// rewards of this run. Only exact upstream own-miner totals are accepted.
	if logOffset < 0 || fi.Size() < logOffset {
		logOffset = fi.Size()
		return
	}
	if fi.Size() == logOffset {
		return
	}
	start := logOffset
	if fi.Size()-start > 65536 {
		start = fi.Size() - 65536
	}
	b := make([]byte, fi.Size()-start)
	_, _ = f.ReadAt(b, start)
	logOffset = fi.Size()
	for _, line := range strings.Split(string(b), "\n") {
		idx := strings.Index(line, "totals: confirmed ")
		if idx < 0 {
			continue
		}
		line = strings.TrimSpace(line[idx+len("totals: confirmed "):])
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		n, e := strconv.ParseUint(fields[0], 10, 64)
		if e != nil {
			continue
		}
		minted := strings.Split(line, " | minted ")
		if len(minted) != 2 {
			continue
		}
		amount := strings.Split(minted[1], " | ")[0]
		motes, err := strconv.ParseUint(strings.ReplaceAll(amount, "_", ""), 10, 64)
		if err != nil {
			continue
		}
		// Upstream totals count gross issuance, including the miner fee. Keep
		// integer precision and never present it as the wallet's net income.
		prox := fmt.Sprintf("%s.%06d", pretty(motes/1_000_000), motes%1_000_000)
		rewardText = fmt.Sprintf("Confirmed issuance (including fees): %s PROX | %s transit(s)", prox, pretty(n))
	}
}
func miningStatusText(g gpuStatus, selected string, rate float64) string {
	// Sensor/power pauses and unreachable goals take priority over protection
	// notices, even if the rolling rate still contains earlier active work.
	if waiting := powerWaitText(g, selected); waiting != "" {
		return waiting
	}
	if g.ThermalLimited {
		prefix := "Waiting for work"
		if rate > 0 {
			prefix = "Mining"
		}
		// This is an upper bound: manual 50%/25% modes stay below it.
		if g.PowerTarget != nil {
			return prefix + " | Temperature protection | At most 95% of maximum power"
		}
		return prefix + " | Temperature protection active"
	}
	if rate > 0 {
		return "GPU mining - computing valid work"
	}
	return "Running - waiting for new GPU work"
}
func powerWaitText(g gpuStatus, selected string) string {
	if g.PowerUnreachable {
		return unreachableText(selected, g.PerformanceMode)
	}
	if !g.PowerDispatchPaused {
		return ""
	}
	switch g.PowerStatus {
	case "power_sensor_unavailable", "waiting_for_power_sensor":
		return "Waiting for the board-power sensor - mining paused"
	default:
		return "Power control - mining paused"
	}
}
func unreachableText(selected, runtimeMode string) string {
	mode := selected
	if validMode(runtimeMode) {
		mode = runtimeMode
	}
	percent := map[string]string{"maximum": "100", "balanced": "50", "eco": "25"}[mode]
	if percent == "" {
		return "Power target is below idle consumption - mining paused"
	}
	return percent + "% target is below idle consumption - mining paused"
}
func telemetryText(g gpuStatus) string {
	powerLine := fmt.Sprintf("GPU sensors | Utilization %s | Board %s", sensor(g.Busy, "%"), sensor(g.Power, " W"))
	if g.PowerAverage != nil {
		powerLine += fmt.Sprintf(" | Average %s", sensor(g.PowerAverage, " W"))
	}
	if g.PowerTarget != nil {
		separator := " | "
		if g.PowerAverage != nil {
			separator = " / "
		}
		powerLine += separator + "Target " + sensor(g.PowerTarget, " W")
	}
	return fmt.Sprintf("%s\r\nCore: %s     Hotspot: %s     Memory: %s", powerLine, sensor(g.Edge, " °C"), sensor(g.Hotspot, " °C"), sensor(g.Memory, " °C"))
}

// History is local accepted-proof accounting, not a ledger reward or coin total.
// A missing or invalid record stays unknown instead of becoming a zero.
func readAcceptanceTotal() *uint64 {
	var record struct {
		Schema int     `json:"schema_version"`
		Total  *uint64 `json:"total_accepted"`
	}
	data, err := os.ReadFile(filepath.Join(dataRoot, "logs", "acceptance-totals.json"))
	if err != nil || json.Unmarshal(data, &record) != nil || record.Schema != 1 {
		return nil
	}
	return record.Total
}
func acceptanceCount(value *uint64) string {
	if value == nil {
		return "unknown"
	}
	return pretty(*value)
}
func acceptanceCounters(g *gpuStatus) string {
	total := readAcceptanceTotal()
	pending := false
	if g != nil && total == nil {
		total = g.CumulativeSolutions
		pending = total != nil && g.CumulativePersisted != nil && !*g.CumulativePersisted
	}
	totalText := acceptanceCount(total)
	if pending {
		totalText += " (saving)"
	}
	if g == nil {
		return fmt.Sprintf("Attempts: -    Jobs received: -\r\nLocally accepted: this session - | total %s    Stale: -", totalText)
	}
	return fmt.Sprintf("Attempts: %s    Jobs received: %s\r\nLocally accepted: this session %s | total %s    Stale: %s", pretty(g.Attempts), pretty(g.Jobs), acceptanceCount(&g.Solutions), totalText, pretty(g.Stale))
}

func refresh() {
	current = currentSupervisor()
	running := current.PID > 0
	readDataState()
	refreshSetup(running)
	ready := readyForDevice()
	enabled(startID, controlsAvailable(running) && ready)
	updateWalletControls()
	enabled(stopID, running)
	enableModeControls(controlsAvailable(running))
	if current.PID != previousPID {
		samples = nil
		logOffset = -1
		previousPID = current.PID
		rewardText = "Rewards: check the miner log; accepted solutions are separate."
	}
	if !running {
		state := stoppedStatusText(ready, statusHint)
		if len(devices) == 0 && statusHint != "" {
			state = statusHint
		}
		if starting {
			state = "Preparing to start..."
		}
		if setupRunning {
			state = "GPU setup in progress - mining has not started"
		}
		if deviceListing {
			state = "Looking for supported GPUs..."
		}
		text(statusID, state)
		text(hashID, "GPU attempts/s (last 10 seconds): -")
		text(countersID, acceptanceCounters(nil))
		text(sensorID, "GPU utilization: -    Board power: -\r\nCore: -    Hotspot: -    Memory: -")
		text(rewardID, rewardText)
		return
	}
	g, fresh := readGPU(current)
	if !fresh {
		text(statusID, "Running - checking network/GPU or waiting for work")
		text(hashID, "GPU attempts/s (last 10 seconds): waiting for samples")
		text(countersID, acceptanceCounters(nil))
		text(sensorID, "Waiting for current GPU sensor readings.\r\nOpen logs for connection details.")
		samples = nil
	} else {
		if len(samples) == 0 || samples[len(samples)-1].at != g.Time {
			if len(samples) > 0 && g.Attempts < samples[len(samples)-1].count {
				samples = nil
			}
			samples = append(samples, sample{g.Time, g.Attempts})
			for len(samples) > 1 && samples[0].at < g.Time-10 {
				samples = samples[1:]
			}
		}
		rate := -1.0
		if len(samples) >= 2 {
			a := samples[0]
			z := samples[len(samples)-1]
			if z.at-a.at >= 1 {
				rate = float64(z.count-a.count) / (z.at - a.at)
			}
		}
		text(statusID, miningStatusText(g, selectedMode, rate))
		speed := "Measuring"
		if rate >= 0 {
			speed = fmt.Sprintf("%.0f H/s", rate)
		}
		text(hashID, "GPU attempts/s (last 10 seconds): "+speed)
		text(countersID, acceptanceCounters(&g))
		text(sensorID, telemetryText(g))
	}
	updateRewards()
	text(rewardID, rewardText)
}
func openPath(path string) {
	r, _, _ := shell.NewProc("ShellExecuteW").Call(hwnd, uintptr(unsafe.Pointer(u("open"))), uintptr(unsafe.Pointer(u(path))), 0, uintptr(unsafe.Pointer(u(root))), 1)
	if r <= 32 {
		message("Cannot open this file or folder.", "Could not open", 0x10)
	}
}
func copyAddress(address string) bool {
	r, _, _ := user.NewProc("OpenClipboard").Call(hwnd)
	if r == 0 {
		return false
	}
	defer user.NewProc("CloseClipboard").Call()
	utf, _ := syscall.UTF16FromString(address)
	size := uintptr(len(utf) * 2)
	mem, _, _ := kernel.NewProc("GlobalAlloc").Call(2, size)
	if mem == 0 {
		return false
	}
	ptr, _, _ := kernel.NewProc("GlobalLock").Call(mem)
	if ptr == 0 {
		kernel.NewProc("GlobalFree").Call(mem)
		return false
	}
	copy(unsafe.Slice((*uint16)(unsafe.Pointer(ptr)), len(utf)), utf)
	kernel.NewProc("GlobalUnlock").Call(mem)
	user.NewProc("EmptyClipboard").Call()
	r, _, _ = user.NewProc("SetClipboardData").Call(13, mem)
	if r == 0 {
		kernel.NewProc("GlobalFree").Call(mem)
		return false
	}
	return true
}
func showAddress() {
	var p struct {
		Holder string `json:"holder_id"`
	}
	b, e := os.ReadFile(filepath.Join(dataRoot, "wallet", "public.json"))
	if e != nil || json.Unmarshal(b, &p) != nil || len(p.Holder) != 64 {
		message("Cannot read the public wallet address. Run setup first.", "Wallet address", 0x10)
		return
	}
	for _, c := range p.Holder {
		if !strings.ContainsRune("0123456789abcdefABCDEF", c) {
			message("The public wallet address is invalid.", "Wallet address", 0x10)
			return
		}
	}
	addr := "a/" + p.Holder
	note := "Use this public address to check the reward account."
	if copyAddress(addr) {
		note = "The public address was copied to the clipboard."
	}
	message("My wallet address\r\n\r\n"+addr+"\r\n\r\n"+note, "Wallet address", 0x40)
}
func showPassword() {
	b, e := os.ReadFile(filepath.Join(dataRoot, "wallet", "unlock.dpapi"))
	if e != nil || len(b) == 0 || len(b) > 65536 {
		message("This Windows account cannot unlock the wallet passphrase.", "Wallet passphrase", 0x10)
		return
	}
	in := dataBlob{Size: uint32(len(b)), Data: &b[0]}
	var out dataBlob
	r, _, _ := crypt.NewProc("CryptUnprotectData").Call(uintptr(unsafe.Pointer(&in)), 0, 0, 0, 0, 1, uintptr(unsafe.Pointer(&out)))
	for i := range b {
		b[i] = 0
	}
	if r == 0 || out.Data == nil || out.Size == 0 {
		message("This Windows account cannot unlock the wallet passphrase.", "Wallet passphrase", 0x10)
		return
	}
	raw := unsafe.Slice(out.Data, int(out.Size))
	if out.Size > 4096 {
		for i := range raw {
			raw[i] = 0
		}
		kernel.NewProc("LocalFree").Call(uintptr(unsafe.Pointer(out.Data)))
		return
	}
	// Display is local and only initiated by this explicit button click. Never
	// write the password to a log, clipboard, command line, or another process.
	caption := u("Wallet passphrase - keep your screen private")
	content, _ := syscall.UTF16FromString("Wallet file passphrase:\r\n\r\n" + string(raw) + "\r\n\r\nClose this dialog to hide it.\r\nKeep the passphrase in a secure offline location for recovery.")
	for i := range raw {
		raw[i] = 0
	}
	kernel.NewProc("LocalFree").Call(uintptr(unsafe.Pointer(out.Data)))
	if len(content) > 0 {
		user.NewProc("MessageBoxW").Call(hwnd, uintptr(unsafe.Pointer(&content[0])), uintptr(unsafe.Pointer(caption)), 0x40)
		for i := range content {
			content[i] = 0
		}
	}
}
func backupWallet() {
	p := filepath.Join(root, "scripts", "Backup-Wallet.ps1")
	if _, e := os.Stat(p); e != nil {
		message("The wallet backup tool is missing. Read the readme.", "Wallet backup", 0x10)
		return
	}
	exe := filepath.Join(os.Getenv("SystemRoot"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	cmd := exec.Command(exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-File", p)
	cmd.Env = childEnvironment()
	cmd.Dir = root
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	if e := cmd.Start(); e != nil {
		message("Could not start the wallet backup tool.", "Wallet backup", 0x10)
		return
	}
	go func() { _ = cmd.Wait() }()
}

func diagnosticsCommand() *exec.Cmd {
	cmd := exec.Command(filepath.Join(root, "tools", "python", "python.exe"), "-X", "utf8", "-u", filepath.Join(root, "miner", "diagnostics.py"))
	cmd.Dir = root
	cmd.Env = childEnvironment()
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	return cmd
}
func diagnosticsArchivePath() (string, error) {
	var record struct {
		Path string `json:"path"`
	}
	data, err := os.ReadFile(filepath.Join(dataRoot, "logs", "diagnostics-export.json"))
	if err != nil || json.Unmarshal(data, &record) != nil || record.Path == "" {
		return "", fmt.Errorf("diagnostics export record is unavailable")
	}
	output, err := filepath.Abs(record.Path)
	if err != nil {
		return "", err
	}
	directory, err := filepath.Abs(filepath.Join(dataRoot, "diagnostics"))
	if err != nil {
		return "", err
	}
	relative, err := filepath.Rel(directory, output)
	if err != nil || relative == "." || filepath.IsAbs(relative) || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || !strings.EqualFold(filepath.Ext(output), ".zip") {
		return "", fmt.Errorf("invalid diagnostics archive location")
	}
	info, err := os.Stat(output)
	if err != nil || info.IsDir() {
		return "", fmt.Errorf("diagnostics archive is missing")
	}
	return output, nil
}
func exportDiagnostics() {
	if diagnosticsRunning {
		return
	}
	diagnosticsRunning = true
	enabled(diagnosticsID, false)
	text(diagnosticsID, "Exporting...")
	go func() {
		cmd := diagnosticsCommand()
		cmd.Stdout = io.Discard
		cmd.Stderr = io.Discard
		err := cmd.Run()
		diagnosticsEvents <- err == nil
		user.NewProc("PostMessageW").Call(hwnd, wmDiagnosticsDone, 0, 0)
	}()
}
func finishDiagnostics() {
	select {
	case success := <-diagnosticsEvents:
		diagnosticsRunning = false
		enabled(diagnosticsID, true)
		text(diagnosticsID, "Export diagnostics")
		path, err := diagnosticsArchivePath()
		if !success || err != nil {
			message("Could not export diagnostics. Open logs for details.", "Diagnostics export", 0x30)
			return
		}
		message("Diagnostics exported:\r\n\r\n"+path+"\r\n\r\nReview the archive before sharing it.", "Diagnostics export", 0x40)
	default:
	}
}

func showBalance() {
	p := filepath.Join(root, "Wallet-Balance.exe")
	cmd := exec.Command(p)
	cmd.Env = childEnvironment()
	cmd.Dir = root
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	if e := cmd.Start(); e != nil {
		message("Could not start the wallet balance viewer.", "Wallet balance", 0x10)
		return
	}
	go func() { _ = cmd.Wait() }()
}
func windowProc(window uintptr, m uint32, w, l uintptr) uintptr {
	switch m {
	case wmCreate:
		hwnd = window
		createControls()
		return 0
	case wmCommand:
		switch int(w & 0xffff) {
		case chooseDeviceID:
			toggleDeviceChoice()
		case diagnosticsID:
			exportDiagnostics()
		case setupID:
			startSetup()
		case deviceComboID:
			if (w>>16)&0xffff == 1 {
				clearUnsupportedSelection()
				refresh()
			}
		case startID:
			startMining()
		case stopID:
			stopMining()
		case logsID:
			openPath(filepath.Join(dataRoot, "logs"))
		case guideID:
			openPath(filepath.Join(root, "README.txt"))
		case addressID:
			showAddress()
		case passwordID:
			showPassword()
		case backupID:
			backupWallet()
		case balanceID:
			showBalance()
		case maxModeID:
			chooseMode("maximum")
		case balancedModeID:
			chooseMode("balanced")
		case ecoModeID:
			chooseMode("eco")

		}
		return 0
	case wmDevices:
		finishDeviceList()
		return 0
	case wmDiagnosticsDone:
		finishDiagnostics()
		return 0
	case wmSetupDone:
		finishSetup()
		return 0
	case wmTimer:
		refresh()
		return 0
	case wmClose:
		if setupRunning {
			message("GPU setup is still running. Please wait for it to finish before closing.", "Setup in progress", 0x40)
			return 0
		}
		if currentSupervisor().PID > 0 {
			answer := message("Mining is running. Keep mining after closing this window?\r\n\r\nYes: continue mining in the background\r\nNo: stop mining and close\r\nCancel: return to this window", "Close window", 0x23)
			if answer == 2 {
				return 0
			}
			if answer == 7 && !stopMining() {
				return 0
			}
		}
		user.NewProc("DestroyWindow").Call(window)
		return 0
	case wmDestroy:
		user.NewProc("PostQuitMessage").Call(0)
		return 0
	}
	r, _, _ := defWindow.Call(window, uintptr(m), w, l)
	return r
}
func main() {
	runtime.LockOSThread()
	exe, e := os.Executable()
	if e != nil {
		return
	}
	root = filepath.Dir(exe)
	dataRoot, e = resolveDataRoot()
	if e != nil {
		message("Cannot locate the local application data folder.", "Startup error", 0x10)
		return
	}
	if e = ensureDataDirectories(); e != nil {
		message("Cannot create the local application data folder.", "Startup error", 0x10)
		return
	}
	digest := sha256.Sum256([]byte(strings.ToLower(filepath.Clean(dataRoot))))
	instanceKey := fmt.Sprintf("%x", digest[:8])
	user.NewProc("SetProcessDPIAware").Call()
	className := "ProximaGpuMinerBeta_" + instanceKey
	mutex, _, mutexErr := kernel.NewProc("CreateMutexW").Call(0, 0, uintptr(unsafe.Pointer(u("Local\\ProximaGpuMinerBeta_"+instanceKey))))
	if mutex == 0 {
		return
	}
	defer kernel.NewProc("CloseHandle").Call(mutex)
	if mutexErr == syscall.Errno(183) {
		existing, _, _ := user.NewProc("FindWindowW").Call(uintptr(unsafe.Pointer(u(className))), 0)
		if existing != 0 {
			user.NewProc("ShowWindow").Call(existing, 9)
			user.NewProc("SetForegroundWindow").Call(existing)
		}
		return
	}
	instance, _, _ := kernel.NewProc("GetModuleHandleW").Call(0)
	cursor, _, _ := user.NewProc("LoadCursorW").Call(0, 32512)
	icon, _, _ := user.NewProc("LoadIconW").Call(0, 32512)
	wc := windowClass{Size: uint32(unsafe.Sizeof(windowClass{})), Style: 3, WndProc: syscall.NewCallback(windowProc), Instance: instance, Cursor: cursor, Icon: icon, Background: 6, ClassName: u(className)}
	r, _, _ := user.NewProc("RegisterClassExW").Call(uintptr(unsafe.Pointer(&wc)))
	if r == 0 {
		return
	}
	bounds := rect{Right: 820, Bottom: 840}
	style := uintptr(0x00ca0000)
	user.NewProc("AdjustWindowRect").Call(uintptr(unsafe.Pointer(&bounds)), style, 0)
	width := bounds.Right - bounds.Left
	height := bounds.Bottom - bounds.Top
	sw, _, _ := user.NewProc("GetSystemMetrics").Call(0)
	sh, _, _ := user.NewProc("GetSystemMetrics").Call(1)
	x := (int32(sw) - width) / 2
	y := (int32(sh) - height) / 2
	if y < 0 {
		y = 0
	}
	hwnd, _, _ = createWindow.Call(0, uintptr(unsafe.Pointer(u(className))), uintptr(unsafe.Pointer(u("Proxima GPU Miner - Windows Beta 0.1.0"))), style, uintptr(x), uintptr(y), uintptr(width), uintptr(height), 0, 0, instance, 0)
	if hwnd == 0 {
		return
	}
	user.NewProc("ShowWindow").Call(hwnd, 5)
	user.NewProc("UpdateWindow").Call(hwnd)
	var m msg
	for {
		r, _, _ = user.NewProc("GetMessageW").Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if r == 0 || r == ^uintptr(0) {
			break
		}
		if handled, _, _ := user.NewProc("IsDialogMessageW").Call(hwnd, uintptr(unsafe.Pointer(&m))); handled == 0 {
			user.NewProc("TranslateMessage").Call(uintptr(unsafe.Pointer(&m)))
			user.NewProc("DispatchMessageW").Call(uintptr(unsafe.Pointer(&m)))
		}
	}
	for _, font := range []uintptr{normalFont, titleFont, statusFont} {
		gdi.NewProc("DeleteObject").Call(font)
	}
}

// Native Windows entry point for the Python OpenCL seeker and upstream tests.
package main

import (
	"encoding/binary"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

func dataWorkDir() (string, error) {
	dataRoot := os.Getenv("PROXIMA_MINER_DATA")
	if dataRoot == "~" || strings.HasPrefix(dataRoot, `~\`) || strings.HasPrefix(dataRoot, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		dataRoot = filepath.Join(home, strings.TrimLeft(dataRoot[1:], `/\`))
	}
	if dataRoot == "" {
		local := os.Getenv("LOCALAPPDATA")
		if local == "" {
			return "", os.ErrNotExist
		}
		dataRoot = filepath.Join(local, "ProximaGpuMinerBeta", "take1")
	}
	abs, err := filepath.Abs(dataRoot)
	if err != nil {
		return "", err
	}
	work := filepath.Join(abs, "work")
	if err = os.MkdirAll(filepath.Join(work, "ocl-cache"), 0700); err != nil {
		return "", err
	}
	return work, nil
}

func main() {
	exe, err := os.Executable()
	if err != nil {
		os.Exit(1)
	}
	root := filepath.Dir(filepath.Dir(exe))
	work, err := dataWorkDir()
	if err != nil {
		os.Stderr.WriteString("Cannot create the miner's local work folder.\n")
		os.Exit(1)
	}
	// Put this entry point and inherited children in a kill-on-close Windows job.
	// Stopping the launcher must also stop Python and its local key helper.
	dll := syscall.NewLazyDLL("kernel32.dll")
	job, _, _ := dll.NewProc("CreateJobObjectW").Call(0, 0)
	if job == 0 {
		os.Exit(1)
	}
	info := make([]byte, 144)
	binary.LittleEndian.PutUint32(info[16:], 0x2000)
	ok, _, _ := dll.NewProc("SetInformationJobObject").Call(job, 9, uintptr(unsafe.Pointer(&info[0])), uintptr(len(info)))
	if ok == 0 {
		os.Exit(1)
	}
	current, _ := syscall.GetCurrentProcess()
	ok, _, _ = dll.NewProc("AssignProcessToJobObject").Call(job, uintptr(current))
	if ok == 0 {
		os.Exit(1)
	}
	os.Setenv("PYTHONUTF8", "1")
	os.Setenv("PYTHONDONTWRITEBYTECODE", "1")
	os.Setenv("AMD_OCL_CACHE_ENABLE", "0")
	os.Setenv("AMD_OCL_CACHE_PATH", filepath.Join(work, "ocl-cache"))
	os.Setenv("TEMP", work)
	os.Setenv("TMP", work)
	args := append([]string{"-u", filepath.Join(root, "miner", "seeker.py")}, os.Args[1:]...)
	cmd := exec.Command(filepath.Join(root, "tools", "python", "python.exe"), args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if e := cmd.Run(); e != nil {
		os.Exit(1)
	}
}

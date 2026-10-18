// Wallet balance viewer. This program reads public data only and never unlocks a key.
package main

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

type amount struct {
	Outputs uint64 `json:"outputs"`
	Motes   uint64 `json:"motes"`
	PROX    string `json:"prox"`
}

type balances struct {
	Ordinary   amount `json:"ordinary"`
	Delegation amount `json:"delegation"`
	OtherChain amount `json:"other_chain"`
	Total      amount `json:"total"`
}

type result struct {
	Status    string    `json:"status"`
	CheckedAt string    `json:"checked_at"`
	Address   string    `json:"address,omitempty"`
	Balances  *balances `json:"balances,omitempty"`
	LRB       string    `json:"lrb,omitempty"`
	Error     string    `json:"error,omitempty"`
	LogPath   string    `json:"log_path,omitempty"`
}

var patterns = []*regexp.Regexp{
	regexp.MustCompile(`(?m)^\s*on\s+([0-9]+) non-chain outputs:\s+([0-9][0-9_]*)\s*$`),
	regexp.MustCompile(`(?m)^\s*on\s+([0-9]+) delegation outputs:\s+([0-9][0-9_]*)\s*$`),
	regexp.MustCompile(`(?m)^\s*on\s+([0-9]+) non-delegation chain outputs:\s+([0-9][0-9_]*)\s*$`),
	regexp.MustCompile(`(?m)^TOTAL controlled on ([0-9]+) outputs:\s+([0-9][0-9_]*)\s*$`),
}

func parseBalances(output string) (*balances, error) {
	values := make([]amount, len(patterns))
	for i, pattern := range patterns {
		matches := pattern.FindAllStringSubmatch(output, -1)
		if len(matches) != 1 {
			return nil, errors.New("Could not verify all four official balance entries. This is not a zero balance.")
		}
		count, err := strconv.ParseUint(matches[0][1], 10, 64)
		if err != nil {
			return nil, errors.New("Invalid output count.")
		}
		motes, err := strconv.ParseUint(strings.ReplaceAll(matches[0][2], "_", ""), 10, 64)
		if err != nil {
			return nil, errors.New("Invalid balance amount.")
		}
		values[i] = amount{count, motes, fmt.Sprintf("%d.%06d", motes/1000000, motes%1000000)}
	}
	sum, count := uint64(0), uint64(0)
	for _, a := range values[:3] {
		if ^uint64(0)-sum < a.Motes || ^uint64(0)-count < a.Outputs {
			return nil, errors.New("The balance total exceeds the supported range.")
		}
		sum += a.Motes
		count += a.Outputs
	}
	if values[3].Motes != sum || values[3].Outputs != count {
		return nil, errors.New("The detail amounts do not match the total. Check the original log.")
	}
	return &balances{values[0], values[1], values[2], values[3]}, nil
}

func balanceDataRoot() (string, error) {
	if v := strings.TrimSpace(os.Getenv("PROXIMA_MINER_DATA")); v != "" {
		return filepath.Abs(v)
	}
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		return "", errors.New("LOCALAPPDATA is unavailable")
	}
	return filepath.Abs(filepath.Join(local, "ProximaGpuMinerBeta", "take1"))
}
func query() result {
	ret := result{Status: "error", CheckedAt: time.Now().Format(time.RFC3339)}
	executable, err := os.Executable()
	if err != nil {
		ret.Error = "Cannot locate the application folder."
		return ret
	}
	root := filepath.Dir(executable)
	dataRoot, err := balanceDataRoot()
	if err != nil {
		ret.Error = "Cannot locate the local application data folder."
		return ret
	}
	ret.LogPath = filepath.Join(dataRoot, "logs", "wallet-balance.log")
	publicBytes, err := os.ReadFile(filepath.Join(dataRoot, "wallet", "public.json"))
	if err != nil {
		ret.Error = "Cannot read the wallet public address file. Run GPU and wallet setup."
		return ret
	}
	var public struct {
		HolderID string `json:"holder_id"`
	}
	if json.Unmarshal(publicBytes, &public) != nil {
		ret.Error = "The public address file is invalid."
		return ret
	}
	holder, err := hex.DecodeString(public.HolderID)
	if err != nil || len(holder) != 32 {
		ret.Error = "The public wallet address is invalid."
		return ret
	}
	ret.Address = "a/" + hex.EncodeToString(holder)
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, filepath.Join(root, "tools", "proxi.exe"), "node", "balance", "--target", ret.Address)
	cmd.Dir = filepath.Join(dataRoot, "wallet")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	// Filter names only; never read or use either secret in a query.
	for _, entry := range os.Environ() {
		name, _, _ := strings.Cut(entry, "=")
		if strings.EqualFold(name, "PROXIMA_KEY_PASSPHRASE") || strings.EqualFold(name, "NONCE_SEEKER_SEED") {
			continue
		}
		cmd.Env = append(cmd.Env, entry)
	}
	cmd.Env = append(cmd.Env, "PROXIMA_MINER_DATA="+dataRoot)
	raw, runErr := cmd.CombinedOutput()
	logErr := os.MkdirAll(filepath.Dir(ret.LogPath), 0700)
	if logErr == nil {
		logErr = os.WriteFile(ret.LogPath, raw, 0600)
	}
	if logErr != nil {
		ret.LogPath = ""
	}
	output := strings.ReplaceAll(string(raw), "\r\n", "\n")
	if match := regexp.MustCompile(`(?m)^Latest reliable branch \(LRB\) txid:\s*(\S+)\s*$`).FindStringSubmatch(output); len(match) == 2 {
		ret.LRB = match[1]
	}
	if runErr != nil {
		if ctx.Err() != nil {
			ret.Error = "The node balance query timed out after 45 seconds. Try again later."
		} else {
			ret.Error = "The public node balance query failed. This is not a zero balance."
		}
		return ret
	}
	lower := strings.ToLower(output)
	if strings.Contains(lower, "warning:") || strings.Contains(lower, "results are partial") || strings.Contains(lower, "iteration cap") {
		ret.Status = "partial"
		ret.Error = "The node returned a warning or partial results. They are not displayed as a complete balance. Check the original log."
		return ret
	}
	ret.Balances, err = parseBalances(output)
	if err != nil {
		ret.Error = err.Error()
		return ret
	}
	ret.Status = "ok"
	if logErr != nil {
		ret.Error = "The query succeeded but the local log could not be saved."
	}
	return ret
}

func message(ret result) string {
	lines := []string{"Checked at: " + ret.CheckedAt}
	if ret.Address != "" {
		lines = append(lines, "Wallet: "+ret.Address)
	}
	if ret.Status == "ok" && ret.Balances != nil {
		b := ret.Balances
		lines = append(lines, "", "Current total balance: "+b.Total.PROX+" PROX", "", "Ordinary balance: "+b.Ordinary.PROX+" PROX", "Delegated balance: "+b.Delegation.PROX+" PROX", "Other chain balance: "+b.OtherChain.PROX+" PROX", "", "The total includes delegated funds.", "This is the current balance, not lifetime mining revenue.", "It may also reflect inflation, deposits and withdrawals.", "GPU attempts are not the number of coins earned.")
	} else {
		lines = append(lines, "", "Balance query "+map[string]string{"partial": "incomplete", "error": "failed"}[ret.Status], "The amount could not be verified; this does not mean 0 PROX.")
	}
	if ret.Error != "" {
		lines = append(lines, "", ret.Error)
	}
	if ret.LRB != "" {
		lines = append(lines, "", "Reference LRB: "+ret.LRB)
	}
	if ret.LogPath != "" {
		lines = append(lines, "", "Public query log: "+ret.LogPath)
	}
	return strings.Join(lines, "\r\n")
}

func main() {
	ret := query()
	if len(os.Args) == 2 && os.Args[1] == "--check" {
		json.NewEncoder(os.Stdout).Encode(ret)
		if ret.Status != "ok" {
			os.Exit(1)
		}
		return
	}
	title, _ := syscall.UTF16PtrFromString("Proxima Take 1 wallet balance")
	body, _ := syscall.UTF16PtrFromString(message(ret))
	icon := uintptr(0x40)
	if ret.Status != "ok" {
		icon = 0x30
	}
	syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(body)), uintptr(unsafe.Pointer(title)), icon)
}

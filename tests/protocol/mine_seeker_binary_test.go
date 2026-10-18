package mine

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/lunfardo314/proxima/ledger/txbuildercore"
	"github.com/lunfardo314/proxima/util/keystore"
	"github.com/lunfardo314/proxima/util/vrf"
	"github.com/stretchr/testify/require"
)

// Local interoperability test using ephemeral synthetic test keys only.
// The endpoint is Go httptest on loopback; no public mining node or real wallet
// is involved. Explicit NONCE_SEEKER_BIN and isolated PROXIMA_MINER_DATA are
// required. The selected GPU does perform a short correctness workload.
// Run through tests/validate_build.py after Build-ProtocolTest.ps1.
func TestNonceSeekerBinary(t *testing.T) {
	// The validation launcher attaches this process to a kill-on-close job
	// before opening the gate, so no GPU child can escape on a timeout.
	if gate := os.Getenv("PROXIMA_PROTOCOL_START_GATE"); gate != "" {
		deadline := time.Now().Add(10 * time.Second)
		for {
			if _, err := os.Stat(gate); err == nil {
				break
			}
			if !time.Now().Before(deadline) {
				t.Fatal("validation containment gate timed out")
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
	bin := os.Getenv("NONCE_SEEKER_BIN")
	if bin == "" {
		t.Skip("NONCE_SEEKER_BIN not set")
	}
	const passphrase = "a passphrase of some length"
	// This overlay additionally verifies the standalone client's persistent
	// local acceptance counters. An explicit isolated data root is mandatory.
	dataRoot := os.Getenv("PROXIMA_MINER_DATA")
	require.NotEmpty(t, dataRoot, "set an isolated PROXIMA_MINER_DATA for this test")
	totalsPath := filepath.Join(dataRoot, "logs", "acceptance-totals.json")
	type acceptanceSnapshot struct {
		Total    int64            `json:"total_accepted"`
		Migrated int64            `json:"migrated_log_count"`
		Sessions map[string]int64 `json:"session_counts"`
	}
	readAcceptanceTotals := func() (acceptanceSnapshot, error) {
		result := acceptanceSnapshot{Sessions: make(map[string]int64)}
		payload, err := os.ReadFile(totalsPath)
		if os.IsNotExist(err) {
			return result, nil
		}
		if err != nil {
			return result, err
		}
		err = json.Unmarshal(payload, &result)
		return result, err
	}
	initialTotals, err := readAcceptanceTotals()
	require.NoError(t, err)

	run := func(t *testing.T, encrypted bool) {
		baseline, err := readAcceptanceTotals()
		require.NoError(t, err)
		e := newSeekerTestEnv(t, "tok")
		dir := t.TempDir()
		keyFile := filepath.Join(dir, "proxima.key")
		sk := e.sk
		var ks *keystore.Keystore
		if encrypted {
			ks, err = keystore.Encrypt(keystore.KeyTypeED25519, sk, e.pk, passphrase, "holder")
		} else {
			ks, err = keystore.NewUnencrypted(keystore.KeyTypeED25519, sk, e.pk, "holder")
		}
		require.NoError(t, err)
		b, err := json.Marshal(ks)
		require.NoError(t, err)
		require.NoError(t, os.WriteFile(keyFile, b, 0o600))

		cmd := exec.Command(bin, "--proxi", e.http.URL, "--token", "tok", "--key-file", keyFile, "--threads", "2", "--name", "rust")
		cmd.Env = append(os.Environ(), "PROXIMA_KEY_PASSPHRASE="+passphrase)
		out, err := os.Create(filepath.Join(dir, "seeker.log"))
		require.NoError(t, err)
		cmd.Stdout, cmd.Stderr = out, out
		require.NoError(t, cmd.Start())
		t.Cleanup(func() {
			_ = cmd.Process.Kill()
			_ = cmd.Wait()
			logBytes, _ := os.ReadFile(filepath.Join(dir, "seeker.log"))
			t.Logf("seeker log:\n%s", logBytes)
			_ = out.Close() // Windows parent log handle cleanup.
		})

		// One job for the whole round. The first solution is accepted and the
		// seeker searches on in the same job, under the beat the answer gave
		// it, so the next solution arrives with no new job published.
		const slot, k = 42, 10
		results := e.srv.publish(e.pred, slot, k, nil, time.Now().Add(time.Minute))
		var prev []byte
		for i := 0; i < 2; i++ {
			var sol mineSolution
			select {
			case sol = <-results:
			case <-time.After(60 * time.Second):
				t.Fatalf("no solution %d from the seeker in 60s", i+1)
			}
			beta, err := vrf.Verify(e.pk, txbuildercore.MineVRFMessage(e.pred, slot, sol.nonce), sol.proof)
			require.NoError(t, err)
			require.GreaterOrEqual(t, trailingZeroBits(beta), k)
			if prev != nil {
				require.Less(t, string(beta), string(prev), "an improvement must beat the previous solution")
			}
			prev = beta
		}
		e.srv.retire()

		// Server acceptance happens before the client receives the HTTP response.
		// Do not kill the client until it has acknowledged and persisted both
		// improvements; then cleanup deliberately kills it without graceful exit.
		persistDeadline := time.Now().Add(5 * time.Second)
		var persisted acceptanceSnapshot
		var persistErr error
		var clientAccepted, newSessions int
		var sessionDelta int64
		for {
			logBytes, logErr := os.ReadFile(filepath.Join(dir, "seeker.log"))
			clientAccepted = 0
			if logErr == nil {
				for _, line := range strings.Split(string(logBytes), "\n") {
					if strings.TrimSpace(line) == "Verified GPU solution accepted; continuing same job" {
						clientAccepted++
					}
				}
			}
			persisted, persistErr = readAcceptanceTotals()
			sessionDelta, newSessions = 0, 0
			if persistErr == nil {
				for id, count := range persisted.Sessions {
					sessionDelta += count - baseline.Sessions[id]
					if _, exists := baseline.Sessions[id]; !exists && count > 0 {
						newSessions++
					}
				}
			}
			if logErr == nil && persistErr == nil && clientAccepted >= 2 &&
				persisted.Total >= baseline.Total+2 && sessionDelta >= 2 {
				break
			}
			if !time.Now().Before(persistDeadline) {
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
		require.NoError(t, persistErr, "client acceptance totals must be readable")
		require.GreaterOrEqual(t, clientAccepted, 2, "client must acknowledge both accepted improvements")
		require.Equal(t, baseline.Total+2, persisted.Total, "both accepted improvements must be persisted exactly once before abrupt termination")
		require.Equal(t, int64(2), sessionDelta, "this client session must persist both acceptances")
		require.Equal(t, 1, newSessions, "a restarted client must create a new session ID")
		require.Equal(t, baseline.Migrated, persisted.Migrated, "restart must not migrate historical events twice")
		for id, count := range baseline.Sessions {
			require.Equal(t, count, persisted.Sessions[id], "previous session counts must survive restart")
		}

		// attempts arrive by report or with the results
		deadline := time.Now().Add(5 * time.Second)
		for e.srv.pendingAttempts() == 0 && time.Now().Before(deadline) {
			time.Sleep(100 * time.Millisecond)
		}
		require.NotZero(t, e.srv.pendingAttempts())
		require.Contains(t, e.srv.summary(), "rust ")
	}
	t.Run("unencrypted key", func(t *testing.T) { run(t, false) })
	t.Run("encrypted key", func(t *testing.T) { run(t, true) })
	finalTotals, err := readAcceptanceTotals()
	require.NoError(t, err)
	require.Equal(t, initialTotals.Total+4, finalTotals.Total, "four accepted improvements must survive both abrupt process exits")
}

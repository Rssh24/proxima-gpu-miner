// Local-only helper. JSON stdin/stdout belongs to the seeker process, never logs.
package main
import (
 "bufio"
 "crypto/ed25519"
 "crypto/rand"
 "crypto/sha512"
 "encoding/hex"
 "encoding/json"
 "fmt"
 "os"
 "time"
 "github.com/lunfardo314/proxima/util/vrf"
 "github.com/lunfardo314/proxima/util/keystore"
 "golang.org/x/crypto/blake2b"
)
type request struct { Op string `json:"op"`; Seed string `json:"seed"`; KeyFile string `json:"key_file"`; Passphrase string `json:"passphrase"`; Alpha string `json:"alpha"`; Count int `json:"count"` }
func main(){
 var prover *vrf.Prover;var sk ed25519.PrivateKey
 scan:=bufio.NewScanner(os.Stdin);scan.Buffer(make([]byte,4096),1024*1024)
 enc:=json.NewEncoder(os.Stdout)
 for scan.Scan(){
  var r request;out:=map[string]any{}
  err:=json.Unmarshal(scan.Bytes(),&r)
  if err==nil { switch r.Op {
  case "init":
   if r.KeyFile!="" {var ks *keystore.Keystore;ks,err=keystore.LoadFromFile(r.KeyFile);if err==nil {var raw []byte;raw,err=ks.GetPrivateKey(r.Passphrase);sk=ed25519.PrivateKey(raw)}} else {var seed []byte;seed,err=hex.DecodeString(r.Seed);if err==nil && len(seed)!=32 {err=fmt.Errorf("invalid seed length")};if err==nil {sk=ed25519.NewKeyFromSeed(seed)}}
   if err==nil {prover,err=vrf.NewProver(sk)}
   if err==nil {h:=sha512.Sum512(sk.Seed());h[0]&=248;h[31]&=127;h[31]|=64;out["scalar"]=hex.EncodeToString(h[:32]);out["pubkey"]=hex.EncodeToString(sk[32:])}
  case "create":
   if _,e:=os.Stat(r.KeyFile);!os.IsNotExist(e){err=fmt.Errorf("key file already exists");break}
   var pk ed25519.PublicKey;pk,sk,err=ed25519.GenerateKey(rand.Reader)
   if err==nil {hid:=blake2b.Sum256(append([]byte{0},pk...));var ks *keystore.Keystore;ks,err=keystore.Encrypt(keystore.KeyTypeED25519,sk,pk,r.Passphrase,hex.EncodeToString(hid[:]));if err==nil {err=ks.SaveToFile(r.KeyFile)};if err==nil {out["pubkey"]=hex.EncodeToString(pk);out["holder_id"]=hex.EncodeToString(hid[:])}}
  case "eval":
   if prover==nil {err=fmt.Errorf("not initialized");break};var a []byte;a,err=hex.DecodeString(r.Alpha)
   if err==nil {var b []byte;var st *vrf.ProofState;b,st,err=prover.Output(a);if err==nil {var proof []byte;proof,err=prover.ProofFor(st);if err==nil {var v []byte;v,err=vrf.Verify(sk.Public().(ed25519.PublicKey),a,proof);if err==nil {out["beta"]=hex.EncodeToString(b);out["verified"]=hex.EncodeToString(v)==hex.EncodeToString(b)}}}}
  case "bench":
   if prover==nil {err=fmt.Errorf("not initialized");break};if r.Count<1||r.Count>1000000 {err=fmt.Errorf("invalid count");break}
   a:=make([]byte,45);t:=time.Now();for i:=0;i<r.Count;i++ {for j:=0;j<8;j++ {a[37+j]=byte(uint64(i)>>(j*8))};_,_,err=prover.Output(a);if err!=nil {break}};out["attempts"]=r.Count;out["seconds"]=time.Since(t).Seconds()
  default:err=fmt.Errorf("unsupported operation")
  }}
  // Never include request fields, key material or underlying errors in diagnostics.
  if err!=nil {out=map[string]any{"error":"local oracle operation failed: "+r.Op}}
  enc.Encode(out)
 }
}

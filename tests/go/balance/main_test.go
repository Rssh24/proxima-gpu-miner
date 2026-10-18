package main
import("os";"path/filepath";"strings";"testing")
func TestPublicBalanceParsing(t *testing.T){
 output:="on 1 non-chain outputs: 1_000_000\non 2 delegation outputs: 2_000_001\non 0 non-delegation chain outputs: 0\nTOTAL controlled on 3 outputs: 3_000_001\n"
 got,err:=parseBalances(output);if err!=nil{t.Fatal(err)};if got.Total.PROX!="3.000001"||got.Total.Outputs!=3{t.Fatal("wrong exact balance")}
 if _,err:=parseBalances(strings.Replace(output,"3_000_001","9_000_000",1));err==nil{t.Fatal("inconsistent total accepted")}
 if _,err:=parseBalances("partial");err==nil{t.Fatal("missing amount treated as zero")}
}
func TestBalanceDataRootIsolation(t *testing.T){v:=filepath.Join(t.TempDir(),"fake-data");t.Setenv("PROXIMA_MINER_DATA",v);got,err:=balanceDataRoot();if err!=nil||got!=v{t.Fatal("balance data override not honored")}}
func TestBalanceAllEnglish(t *testing.T){data,err:=os.ReadFile("main.go");if err!=nil{t.Fatal(err)};for _,r:=range string(data){if r>=0xAC00&&r<=0xD7A3{t.Fatal("Korean balance message remains")}}}

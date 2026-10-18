package main
import("encoding/json";"os";"path/filepath";"reflect";"strings";"testing";"time")
func isolated(t *testing.T){t.Helper();root=t.TempDir();dataRoot=t.TempDir();profile=deviceProfile{};setupInfo=setupStatus{};selectedMode="maximum";modeNeedsChoice=false;starting=false;setupRunning=false;deviceListing=false;statusHint="";if err:=ensureDataDirectories();err!=nil{t.Fatal(err)}}
func TestDataRootIsolation(t *testing.T){
 local:=t.TempDir();override:=filepath.Join(t.TempDir(),"isolated-data")
 t.Setenv("LOCALAPPDATA",local);t.Setenv("PROXIMA_MINER_DATA",override)
 got,err:=resolveDataRoot();if err!=nil||got!=override{t.Fatal("override data root was not honored")}
 t.Setenv("PROXIMA_MINER_DATA","");got,err=resolveDataRoot();if err!=nil||got!=filepath.Join(local,"ProximaGpuMinerBeta","take1"){t.Fatal("default data root is not beta-isolated")}
}
func TestSetupCommandIsExplicitAndIsolated(t *testing.T){
 isolated(t);t.Setenv("PROXIMA_KEY_PASSPHRASE","FAKE-TEST-SECRET");t.Setenv("NONCE_SEEKER_SEED","FAKE-TEST-SEED")
 key:="nvidia-public-device-key"
 cmd:=setupCommand(key)
 want:=[]string{filepath.Join(root,"tools","python","python.exe"),"-X","utf8","-u",filepath.Join(root,"miner","setup.py"),"--device",key}
 if !reflect.DeepEqual(cmd.Args,want)||cmd.Dir!=root||!cmd.SysProcAttr.HideWindow||cmd.SysProcAttr.CreationFlags!=0x08000000{t.Fatal("incorrect setup command")}
 env:=map[string]string{};for _,entry:=range cmd.Env{k,v,_:=strings.Cut(entry,"=");env[strings.ToUpper(k)]=v}
 if env["PROXIMA_MINER_DATA"]!=dataRoot||env["TEMP"]!=filepath.Join(dataRoot,"work"){t.Fatal("setup escaped the isolated data root")}
 if _,ok:=env["PROXIMA_KEY_PASSPHRASE"];ok{t.Fatal("inherited wallet secret was forwarded")};if _,ok:=env["NONCE_SEEKER_SEED"];ok{t.Fatal("inherited seeker secret was forwarded")}
}
func TestControlsDisabledWhileBusy(t *testing.T){
 isolated(t);if !controlsAvailable(false)||controlsAvailable(true){t.Fatal("running control state incorrect")}
 starting=true;if controlsAvailable(false){t.Fatal("controls enabled during start")};starting=false
 setupRunning=true;if controlsAvailable(false){t.Fatal("controls enabled during setup")};setupRunning=false
 deviceListing=true;if controlsAvailable(false){t.Fatal("controls enabled during discovery")}
}
func TestDeviceProfileModes(t *testing.T){
 isolated(t)
 if !modeAvailable("maximum")||modeAvailable("balanced")||modeAvailable("eco"){t.Fatal("missing telemetry did not disable targets")}
 if err:=json.Unmarshal([]byte(`{"device_key":"gpu-1","device_name":"Test GPU","power_available":true,"modes":{"maximum":{"enabled":true},"balanced":{"enabled":false,"reason":"not calibrated"},"eco":{"enabled":true}}}`),&profile);err!=nil{t.Fatal(err)}
 if modeAvailable("balanced")||!modeAvailable("eco"){t.Fatal("per-mode availability was ignored")}
 selectedMode="balanced";if err:=saveModeForStart();err==nil{t.Fatal("unsupported profile allowed mining start")}
}
func TestModePersistenceOnlyWritesUserData(t *testing.T){
 isolated(t);profile.PowerAvailable=true
 for _,mode:=range []string{"maximum","balanced","eco"}{selectedMode=mode;if err:=saveModeForStart();err!=nil{t.Fatal(err)};data,err:=os.ReadFile(filepath.Join(dataRoot,"performance.json"));if err!=nil{t.Fatal(err)};actual,err:=decodeMode(data);if err!=nil||actual!=mode{t.Fatal("mode was not persisted")}}
 if _,err:=os.Stat(filepath.Join(root,"performance.json"));!os.IsNotExist(err){t.Fatal("profile was written into application folder")}
}
func TestSetupRequiredAndDeviceMustMatch(t *testing.T){
 isolated(t)
 if ok,_:=readyForMining("gpu-1");ok{t.Fatal("unconfigured GPU accepted")}
 profile=deviceProfile{Key:"gpu-1",Name:"Test GPU"};setupInfo.State="ready"
 if ok,_:=readyForMining("gpu-1");ok{t.Fatal("missing public wallet accepted")}
 fake:=`{"holder_id":"`+strings.Repeat("a",64)+`"}`
 if err:=os.WriteFile(filepath.Join(dataRoot,"wallet","public.json"),[]byte(fake),0600);err!=nil{t.Fatal(err)}
 for _,name:=range []string{"proxima.key","unlock.dpapi"}{if err:=os.WriteFile(filepath.Join(dataRoot,"wallet",name),[]byte("FAKE TEST FILE"),0600);err!=nil{t.Fatal(err)}}
 if ok,why:=readyForMining("gpu-1");!ok{t.Fatal(why)}
 if ok,_:=readyForMining("gpu-2");ok{t.Fatal("different selected GPU accepted")}
 setupInfo.State="failed";if ok,_:=readyForMining("gpu-1");ok{t.Fatal("failed setup accepted")}
}
func TestStaleGPUDataNotLive(t *testing.T){
 isolated(t);now:=float64(time.Now().UnixNano())/1e9
 data,_:=json.Marshal(gpuStatus{Time:now-20,Attempts:10});if err:=os.WriteFile(filepath.Join(dataRoot,"logs","gpu-status.json"),data,0600);err!=nil{t.Fatal(err)}
 if _,live:=readGPU(supervisor{Started:now-100});live{t.Fatal("stale GPU data treated as current")}
}
func TestEnglishStatusPriority(t *testing.T){
 g:=gpuStatus{ThermalLimited:true,PowerDispatchPaused:true,PowerStatus:"power_sensor_unavailable"}
 if got:=miningStatusText(g,"eco",100);got!="Waiting for the board-power sensor - mining paused"{t.Fatal(got)}
 g.PowerUnreachable=true;if got:=miningStatusText(g,"eco",100);!strings.HasPrefix(got,"25% target"){t.Fatal("power priority lost")}
}
func TestNoHangulOrProductionPaths(t *testing.T){
 data,err:=os.ReadFile("main.go");if err!=nil{t.Fatal(err)}
 for _,r:=range string(data){if r>=0xAC00&&r<=0xD7A3{t.Fatal("non-English Korean UI remains")}}
 if strings.Contains(string(data),`Local\\ProximaTake1Gui`)||strings.Contains(string(data),`C:\Users\`){t.Fatal("production identity/path leaked into beta")}
}
func TestDiagnosticsCommandAndArchiveContainment(t *testing.T){
 isolated(t)
 cmd:=diagnosticsCommand()
 if cmd.Args[len(cmd.Args)-1]!=filepath.Join(root,"miner","diagnostics.py")||cmd.Dir!=root||!cmd.SysProcAttr.HideWindow{t.Fatal("incorrect diagnostics command")}
 dir:=filepath.Join(dataRoot,"diagnostics");if err:=os.MkdirAll(dir,0700);err!=nil{t.Fatal(err)}
 good:=filepath.Join(dir,"Proxima-diagnostics-test.zip");if err:=os.WriteFile(good,[]byte("FAKE TEST ZIP"),0600);err!=nil{t.Fatal(err)}
 record,_:=json.Marshal(map[string]string{"path":good});marker:=filepath.Join(dataRoot,"logs","diagnostics-export.json")
 if err:=os.WriteFile(marker,record,0600);err!=nil{t.Fatal(err)}
 if got,err:=diagnosticsArchivePath();err!=nil||got!=good{t.Fatal("valid isolated export was not accepted")}
 outside:=filepath.Join(root,"outside.zip");if err:=os.WriteFile(outside,[]byte("FAKE"),0600);err!=nil{t.Fatal(err)}
 record,_=json.Marshal(map[string]string{"path":outside});if err:=os.WriteFile(marker,record,0600);err!=nil{t.Fatal(err)}
 if _,err:=diagnosticsArchivePath();err==nil{t.Fatal("external diagnostics path was accepted")}
}
func TestUnsupportedTelemetryDoesNotClaimPowerCap(t *testing.T){
 got:=miningStatusText(gpuStatus{ThermalLimited:true},"maximum",100)
 if !strings.Contains(got,"Temperature protection")||strings.Contains(got,"95%"){t.Fatal("power cap claimed without measured power target")}
}

func TestDefaultGPUUsesComputeUnitsAndPreservesSaved(t *testing.T){
 inventory:=[]publicDevice{{Key:"igpu",Name:"Shared-memory integrated GPU",Memory:36<<30,ComputeUnits:2},{Key:"discrete",Name:"Discrete GPU",Memory:16<<30,ComputeUnits:64}}
 if got:=preferredDeviceIndex(inventory,"");got!=1{t.Fatal("shared-memory size outweighed compute units")}
 if got:=preferredDeviceIndex(inventory,"igpu");got!=0{t.Fatal("saved device selection was not preserved")}
 if got:=preferredDeviceIndex(nil,"");got!=-1{t.Fatal("empty inventory has a selected device")}
}
func TestFirstRunStatusAndWalletGates(t *testing.T){
 isolated(t)
 if got:=stoppedStatusText(false,"");got!="Stopped - run GPU setup first"{t.Fatal("first-run status directs user to mining")}
 if available,unlock:=walletAvailability();available||unlock{t.Fatal("wallet controls enabled without files")}
 for _,name:=range []string{"public.json","proxima.key"}{if err:=os.WriteFile(filepath.Join(dataRoot,"wallet",name),[]byte("FAKE"),0600);err!=nil{t.Fatal(err)}}
 if available,unlock:=walletAvailability();!available||unlock{t.Fatal("wallet file-existence gates are incorrect")}
}
func TestAcceptanceHistoryStoppedUnknownAndKnown(t *testing.T){
 isolated(t)
 if got:=acceptanceCounters(nil);!strings.Contains(got,"this session - | total unknown"){t.Fatal("missing history was not unknown")}
 file:=filepath.Join(dataRoot,"logs","acceptance-totals.json")
 if err:=os.WriteFile(file,[]byte(`{"schema_version":1,"total_accepted":37}`),0600);err!=nil{t.Fatal(err)}
 if got:=acceptanceCounters(nil);!strings.Contains(got,"this session - | total 37"){t.Fatal("stopped persistent total not displayed")}
 total:=uint64(40);g:=gpuStatus{Solutions:2,CumulativeSolutions:&total}
 if got:=acceptanceCounters(&g);!strings.Contains(got,"this session 2 | total 37"){t.Fatal("session and persistent total were not distinct")}
 if err:=os.Remove(file);err!=nil{t.Fatal(err)}
 if got:=acceptanceCounters(&g);!strings.Contains(got,"this session 2 | total 40"){t.Fatal("fresh GPU total fallback missing")}
 if err:=os.WriteFile(file,[]byte(`{"schema_version":1,"total_accepted":0}`),0600);err!=nil{t.Fatal(err)}
 if got:=acceptanceCounters(nil);!strings.Contains(got,"this session - | total 0"){t.Fatal("known zero total was lost")}
}

func TestBetaPendingSaveLabelOnlyOnExplicitUnsavedFallback(t *testing.T){
 isolated(t);total:=uint64(3);yes,no:=true,false
 for _,c:=range []struct{flag *bool;pending bool}{{nil,false},{&yes,false},{&no,true}}{
  text:=acceptanceCounters(&gpuStatus{Solutions:1,CumulativeSolutions:&total,CumulativePersisted:c.flag})
  if strings.Contains(text,"(saving)")!=c.pending{t.Fatal("incorrect pending-save flag handling")}
 }
 if got:=acceptanceCounters(&gpuStatus{CumulativePersisted:&no});strings.Contains(got,"(saving)"){t.Fatal("unknown fallback labeled numeric pending total")}
 if err:=os.WriteFile(filepath.Join(dataRoot,"logs","acceptance-totals.json"),[]byte(`{"schema_version":1,"total_accepted":2}`),0600);err!=nil{t.Fatal(err)}
 text:=acceptanceCounters(&gpuStatus{Solutions:1,CumulativeSolutions:&total,CumulativePersisted:&no})
 if !strings.Contains(text,"total 2")||strings.Contains(text,"(saving)"){t.Fatal("durable file total mislabeled unsaved")}
}
func TestAutomaticDiscreteSelectionAndBackendRecommendation(t *testing.T){
 yes,no:=true,false
 inventory:=[]publicDevice{
  {Key:"integrated",Name:"Integrated",Memory:36<<30,ComputeUnits:128,HostUnified:&yes},
  {Key:"unknown",Name:"Unknown memory type",Memory:16<<30,ComputeUnits:64},
  {Key:"dedicated",Name:"Dedicated",Memory:8<<30,ComputeUnits:32,HostUnified:&no},
 }
 if got:=preferredDeviceIndex(inventory,"");got!=2{t.Fatal("dedicated GPU did not take priority")}
 if got:=preferredDeviceIndex(inventory,"","unknown");got!=1{t.Fatal("backend recommendation was ignored")}
 if got:=preferredDeviceIndex(inventory,"integrated","unknown");got!=0{t.Fatal("saved configuration did not take priority")}
 if got:=preferredDeviceIndex(inventory,"missing","stale");got!=2{t.Fatal("invalid saved/recommended key prevented safe fallback")}
 tie:=[]publicDevice{{Key:"b",ComputeUnits:64,Memory:16<<30},{Key:"a",ComputeUnits:64,Memory:16<<30}}
 if got:=preferredDeviceIndex(tie,"");got!=1{t.Fatal("fallback tie break is not deterministic")}
}
func TestUnifiedMemoryUnknownRemainsDistinct(t *testing.T){
 var inventory struct{Devices []publicDevice `json:"devices"`;Recommended string `json:"recommended_device_key"`}
 data:=`{"devices":[{"device_key":"integrated","host_unified_memory":true},{"device_key":"dedicated","host_unified_memory":false},{"device_key":"unknown","host_unified_memory":null}],"recommended_device_key":"dedicated"}`
 if err:=json.Unmarshal([]byte(data),&inventory);err!=nil{t.Fatal(err)}
 if inventory.Devices[0].HostUnified==nil||!*inventory.Devices[0].HostUnified||inventory.Devices[1].HostUnified==nil||*inventory.Devices[1].HostUnified||inventory.Devices[2].HostUnified!=nil{t.Fatal("memory-type tri-state was lost")}
 if got:=preferredDeviceIndex(inventory.Devices,"",inventory.Recommended);got!=1{t.Fatal("automatic device recommendation was not selected")}
}

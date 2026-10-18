"""Run isolated native GUI/balance logic tests without opening a window."""
import argparse,os,shutil,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--go',required=True)
p.add_argument('--go-cache')
a=p.parse_args()
source=Path(__file__).resolve().parents[1]
work=source/'build/work/gui-tests';work.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,GO111MODULE='off',GOTOOLCHAIN='local',GOTELEMETRY='off',CGO_ENABLED='0',GOFLAGS='')
if a.go_cache:env['GOCACHE']=str(Path(a.go_cache).resolve())
for suite,filename in [('gui','main.go'),('balance','balance.go')]:
    with tempfile.TemporaryDirectory(prefix=suite+'-',dir=work) as tmp:
        tmp=Path(tmp)
        shutil.copy2(source/'app'/filename,tmp/'main.go')
        shutil.copy2(source/'tests/go'/suite/'main_test.go',tmp/'main_test.go')
        subprocess.run([a.go,'test','-count=1','-v'],cwd=tmp,env=env,check=True)
print('Native GUI and balance tests passed; no window or mining process was launched.')

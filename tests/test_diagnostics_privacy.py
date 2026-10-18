"""Diagnostics privacy checks on synthetic files only; no GPU or real wallet."""
import importlib,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch

from bootstrap import MINER, SCRATCH, temporary_directory
diagnostics=importlib.import_module('diagnostics')

class DiagnosticPrivacyTests(unittest.TestCase):
    def test_json_seed_string_is_redacted(self):
        canary='SYNTHETIC_SEED_WORDS_FOR_PRIVACY_TEST'
        self.assertNotIn(canary,diagnostics.scrub(json.dumps({'seed':canary})))

    def test_escaped_non_c_user_profile_is_redacted(self):
        with patch.dict(os.environ,{'USERPROFILE':r'D:\Users\SyntheticAccount'}):
            self.assertNotIn('SyntheticAccount',diagnostics.scrub(json.dumps({'path':r'D:\Users\SyntheticAccount\logs\example.txt'})))

    def test_forward_slash_user_profile_is_redacted(self):
        with patch.dict(os.environ,{'USERPROFILE':r'D:\Users\SyntheticAccount'}):
            self.assertNotIn('SyntheticAccount',diagnostics.scrub('D:/Users/SyntheticAccount/logs/example.txt'))

    def test_export_is_valid_json_and_never_reads_wallet(self):
        with temporary_directory('diagnostics-fixture-') as folder:
            data=Path(folder)/'data';app=Path(folder)/'app'
            (data/'logs').mkdir(parents=True);(app/'tools').mkdir(parents=True);(data/'wallet').mkdir()
            (data/'wallet/proxima.key').write_text('SYNTHETIC_FILE_NOT_A_REAL_KEY')
            (data/'wallet/unlock.dpapi').write_text('SYNTHETIC_FILE_NOT_A_REAL_UNLOCK')
            (data/'logs/live-gpu.log').write_text('Attempts: 1234\npassword = SYNTHETIC_PASSWORD_CANARY\n')
            (data/'logs/unknown-private-file.txt').write_text('SYNTHETIC_NOT_ALLOWLISTED')
            (data/'device-profile.json').write_text(json.dumps({'device_name':'Synthetic GPU','vendor':'TEST','driver':'1','sensor_capabilities':{'core_temperature':True},'power_available':False,'modes':{},'batch':1024,'local':32,'attempts_per_second':1234,'max_batch_seconds':.01,'power_profiles':None,'self_test':{'passed':True}}))
            (app/'tools/build-info.json').write_text(json.dumps({'version':'0.1.0','miner_version':4,'source_commit':'public-test-reference'}))
            original_open=Path.open
            def checked_open(path,*args,**kwargs):
                if path==data/'wallet' or data/'wallet' in path.parents:
                    raise AssertionError('Diagnostics attempted to read a wallet fixture')
                return original_open(path,*args,**kwargs)
            with patch.object(diagnostics,'DATA_ROOT',data),patch.object(diagnostics,'APP_ROOT',app),patch.object(diagnostics,'ensure_data_dirs',lambda:None),patch.object(Path,'open',checked_open):
                archive=diagnostics.export()
            with zipfile.ZipFile(archive) as z:
                names=z.namelist()
                self.assertFalse(any('wallet/' in p or 'unlock' in p or 'proxima.key' in p for p in names))
                alltext='\n'.join(z.read(n).decode() for n in names)
                self.assertNotIn('SYNTHETIC_FILE_NOT_A_REAL_KEY',alltext)
                self.assertNotIn('SYNTHETIC_PASSWORD_CANARY',alltext)
                self.assertNotIn('SYNTHETIC_NOT_ALLOWLISTED',alltext)
                metadata=json.loads(z.read('diagnostics.json'))
                self.assertEqual(metadata['gpu']['device_name'],'Synthetic GPU')

if __name__=='__main__':unittest.main(verbosity=2)

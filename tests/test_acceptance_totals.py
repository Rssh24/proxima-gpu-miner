"""Temporary-data-only persistence tests; never read real miner logs or wallets."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bootstrap import MINER, SCRATCH, temporary_directory
import acceptance_totals as totals_module
from acceptance_totals import AcceptanceTotals,EVENT_LINE


class AcceptanceTotalTests(unittest.TestCase):
    def setUp(self):
        self.base=(SCRATCH/'acceptance-tests').resolve()
        self.base.mkdir(parents=True,exist_ok=True)
        self.root=Path(tempfile.mkdtemp(prefix='case-',dir=self.base)).resolve()
        if not self.root.is_relative_to(self.base): raise RuntimeError('Unexpected test path')
        self.log=self.root/'logs'/'live-gpu.log'; self.log.parent.mkdir()
        self.state_path=self.root/'logs'/'acceptance-totals.json'
        self.writers=[]

    def tearDown(self):
        for writer in self.writers:
            if not writer.closed: writer.close()
        target=self.root.resolve()
        if not target.is_relative_to(self.base) or target==self.base:
            raise RuntimeError('Refusing to remove a path outside the test folder')
        shutil.rmtree(target)

    def writer(self):
        writer=AcceptanceTotals(self.root); self.writers.append(writer); return writer

    def test_missing_log_starts_at_zero(self):
        writer=self.writer(); self.assertEqual(writer.total_accepted,0)
        self.assertTrue(writer.persisted); self.assertEqual(writer.migrated_log_count,0)

    def test_migrates_only_exact_event_lines(self):
        self.log.write_text('\n'.join((EVENT_LINE, '  '+EVENT_LINE+'  ',
                            'prefix '+EVENT_LINE,'{"solutions_accepted":999}',EVENT_LINE+' again')),encoding='utf-8')
        (self.root/'logs'/'protocol-test.log').write_text(EVENT_LINE*5)
        writer=self.writer(); self.assertEqual(writer.total_accepted,2); self.assertEqual(writer.migrated_log_count,2)

    def test_increasing_and_repeated_session_observations(self):
        writer=self.writer()
        self.assertEqual(writer.observe('session-a',0),0)
        self.assertEqual(writer.observe('session-a',3),3)
        self.assertEqual(writer.observe('session-a',3),3)
        self.assertEqual(writer.observe('session-a',5),5)

    def test_session_change_and_return_are_idempotent(self):
        writer=self.writer(); writer.observe('session-a',3); writer.observe('session-b',2)
        self.assertEqual(writer.observe('session-a',3),5)
        self.assertEqual(writer.observe('session-b',4),7)

    def test_lower_count_same_session_rejected(self):
        writer=self.writer(); writer.observe('session-a',3)
        before=self.state_path.read_bytes()
        with self.assertRaises(ValueError): writer.observe('session-a',2)
        self.assertEqual(writer.total_accepted,3); self.assertEqual(self.state_path.read_bytes(),before)

    def test_invalid_counts_rejected_without_mutation(self):
        writer=self.writer()
        for bad in (-1,True,False,1.5,'2',None):
            with self.subTest(bad=bad),self.assertRaises(ValueError): writer.observe('session',bad)
        self.assertEqual(writer.total_accepted,0)

    def test_invalid_session_ids_rejected(self):
        writer=self.writer()
        for bad in ('',' ',None,1,True,'x'*129):
            with self.subTest(bad=bad),self.assertRaises(ValueError): writer.observe(bad,1)

    def test_restart_does_not_remigrate_log(self):
        self.log.write_text(EVENT_LINE+'\n')
        writer=self.writer(); writer.observe('session-a',2); writer.close()
        self.log.write_text((EVENT_LINE+'\n')*5)
        restarted=self.writer()
        self.assertEqual(restarted.total_accepted,3); self.assertEqual(restarted.migrated_log_count,1)
        self.assertEqual(restarted.observe('session-a',2),3)
        self.assertEqual(restarted.observe('session-b',1),4)

    def test_transient_publish_keeps_pending_and_same_count_retry(self):
        writer=self.writer(); original=totals_module.write_status
        with patch.object(totals_module,'write_status',side_effect=[False,False,True]) as fake:
            self.assertEqual(writer.observe('session-a',2),2); self.assertFalse(writer.persisted)
            self.assertEqual(writer.observe('session-a',2),2); self.assertFalse(writer.persisted)
            self.assertEqual(writer.observe('session-a',3),3); self.assertTrue(writer.persisted)
            self.assertEqual(fake.call_count,3)
        # Final fake acknowledgement was a simulation; publish the real state for cleanup.
        writer.persisted=False; writer.observe('session-a',3)
        self.assertEqual(json.loads(self.state_path.read_text())['total_accepted'],3)

    def test_actual_retry_after_sharing_failure_persists_once(self):
        writer=self.writer(); original=totals_module.write_status
        with patch.object(totals_module,'write_status',return_value=False):
            writer.observe('session-a',2)
        self.assertEqual(json.loads(self.state_path.read_text())['total_accepted'],0)
        self.assertEqual(writer.observe('session-a',2),2); self.assertTrue(writer.persisted)
        writer.close(); restarted=self.writer()
        self.assertEqual(restarted.observe('session-a',2),2)

    def test_failed_first_migration_publish_is_not_counted_twice(self):
        self.log.write_text((EVENT_LINE+'\n')*2)
        with patch.object(totals_module,'write_status',return_value=False): writer=self.writer()
        self.assertFalse(writer.persisted); self.assertFalse(self.state_path.exists())
        self.assertEqual(writer.observe('session-a',1),3); self.assertTrue(writer.persisted)
        self.assertEqual(json.loads(self.state_path.read_text())['migrated_log_count'],2)

    def test_close_retries_pending_and_releases_lock(self):
        writer=self.writer()
        with patch.object(totals_module,'write_status',return_value=False): writer.observe('a',4)
        self.assertTrue(writer.close()); self.assertTrue(writer.closed)
        restarted=self.writer(); self.assertEqual(restarted.total_accepted,4)

    def test_close_failure_reports_not_persisted_and_releases_lock(self):
        writer=self.writer()
        with patch.object(totals_module,'write_status',return_value=False):
            writer.observe('a',4); self.assertFalse(writer.close())
        self.assertTrue(writer.closed)
        restarted=self.writer(); self.assertEqual(restarted.total_accepted,0)

    def test_corrupt_json_preserved_and_lock_released(self):
        payload=b'{corrupt'; self.state_path.write_bytes(payload)
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'corrupt'): AcceptanceTotals(self.root)
        self.assertEqual(self.state_path.read_bytes(),payload)

    def test_inconsistent_state_preserved(self):
        value=dict(schema_version=1,total_accepted=99,migrated_log_count=0,session_counts={'a':1})
        payload=json.dumps(value).encode(); self.state_path.write_bytes(payload)
        with self.assertRaisesRegex(RuntimeError,'corrupt'): AcceptanceTotals(self.root)
        self.assertEqual(self.state_path.read_bytes(),payload)

    def test_boolean_persisted_count_rejected(self):
        self.state_path.write_text(json.dumps(dict(schema_version=1,total_accepted=1,migrated_log_count=0,session_counts={'a':True})))
        with self.assertRaisesRegex(RuntimeError,'corrupt'): AcceptanceTotals(self.root)

    def test_duplicate_json_key_rejected(self):
        self.state_path.write_text('{"schema_version":1,"total_accepted":0,"total_accepted":1,"migrated_log_count":0,"session_counts":{}}')
        with self.assertRaisesRegex(RuntimeError,'corrupt'): AcceptanceTotals(self.root)

    def test_same_process_second_writer_blocked(self):
        self.writer()
        with self.assertRaisesRegex(RuntimeError,'Another miner'): AcceptanceTotals(self.root)

    def child(self,code):
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        prefix='import sys;sys.path.insert(0,'+repr(str(MINER))+');from acceptance_totals import AcceptanceTotals;'
        return subprocess.run([sys.executable,'-c',prefix+code],capture_output=True,text=True,timeout=15,env=env)

    def test_cross_process_second_writer_blocked(self):
        self.writer()
        result=self.child('AcceptanceTotals('+repr(str(self.root))+')')
        self.assertNotEqual(result.returncode,0); self.assertIn('Another miner',result.stderr)

    def test_crash_after_ack_releases_lock_and_keeps_total(self):
        result=self.child('import os;writer=AcceptanceTotals('+repr(str(self.root))+');writer.observe("crashed-session",7);os._exit(0)')
        self.assertEqual(result.returncode,0,result.stderr)
        writer=self.writer(); self.assertEqual(writer.total_accepted,7)
        self.assertEqual(writer.observe('crashed-session',7),7)
        self.assertEqual(writer.observe('new-session',1),8)

    def test_observe_after_close_rejected(self):
        writer=self.writer(); writer.close()
        with self.assertRaises(RuntimeError): writer.observe('a',1)

    def test_snapshot_has_only_public_aggregate(self):
        writer=self.writer(); writer.observe('session-a',2)
        snapshot=writer.snapshot(); self.assertEqual(snapshot['total_accepted'],2)
        self.assertEqual(snapshot['session_count'],1); self.assertNotIn('session_counts',snapshot)


if __name__=='__main__': unittest.main(verbosity=2)

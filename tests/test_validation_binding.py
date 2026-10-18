"""No GPU: build evidence must bind to exact safe source/artifact paths."""
import copy
import json
from pathlib import Path
import unittest
from bootstrap import temporary_directory
from validation_common import child_path,sha256,upstream_hashes,verify_hash_map,write_json
from validate_build import verify_build


class ValidationBindingTests(unittest.TestCase):
    def setUp(self):
        self.context=temporary_directory('validation-binding-')
        self.base=Path(self.context.__enter__());self.source=self.base/'source';self.package=self.base/'package'
        for root in (self.source,self.package):
            (root/'miner').mkdir(parents=True);(root/'upstream/util/vrf').mkdir(parents=True)
            (root/'upstream/util/vrf/vrf_test.go').write_text('// synthetic public fixture\n')
            (root/'miner/test.py').write_text('# synthetic source\n')
        (self.source/'tests/protocol').mkdir(parents=True)
        (self.source/'tests/protocol/mine_seeker_binary_test.go').write_text('// synthetic overlay\n')
        (self.package/'tools').mkdir()
        artifacts={}
        for name in ('proxi.exe','oracle.exe','gpu-seeker.exe'):
            path=self.package/'tools'/name;path.write_bytes(b'NON_EXECUTABLE_TEST_FIXTURE')
            artifacts[name]=sha256(path)
        self.info={'source_commit':'synthetic','miner_version':4,'artifacts':artifacts,
                   'seeker_sources':{'test.py':sha256(self.package/'miner/test.py')}}
        self.manifest={'source_sha256':{'miner/test.py':sha256(self.source/'miner/test.py'),
              'upstream/util/vrf/vrf_test.go':sha256(self.source/'upstream/util/vrf/vrf_test.go')},
              'artifact_sha256':{'tools/'+name:digest for name,digest in artifacts.items()}}
        write_json(self.package/'tools/build-info.json',self.info)
        write_json(self.package/'build-manifest.json',self.manifest)
        self.protocol=self.base/'protocol-tests.exe';self.protocol.write_bytes(b'NON_EXECUTABLE_PROTOCOL_FIXTURE')
        self.receipt={'compiled':True,'executable_sha256':sha256(self.protocol),
                      'overlay_sha256':sha256(self.source/'tests/protocol/mine_seeker_binary_test.go'),
                      'upstream_sha256':upstream_hashes(self.source/'upstream')}
        write_json(self.base/'protocol-build.json',self.receipt)

    def tearDown(self):self.context.__exit__(None,None,None)

    def verify(self):return verify_build(self.source,self.package,self.protocol)

    def test_valid_exact_hashes(self):self.assertEqual(self.verify()[0],self.manifest)

    def test_modified_binary_rejected(self):
        (self.package/'tools/oracle.exe').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'hash mismatch'):self.verify()

    def test_modified_miner_source_rejected(self):
        (self.package/'miner/test.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'hash mismatch'):self.verify()

    def test_stale_protocol_overlay_rejected(self):
        (self.source/'tests/protocol/mine_seeker_binary_test.go').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'overlay changed'):self.verify()

    def test_stale_protocol_executable_rejected(self):
        self.protocol.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'compile receipt'):self.verify()

    def test_modified_upstream_protocol_sources_rejected(self):
        (self.source/'upstream/new.go').write_text('// modified upstream\n')
        with self.assertRaisesRegex(RuntimeError,'protocol source changed'):self.verify()

    def test_uncompiled_receipt_rejected(self):
        self.receipt['compiled']=False;write_json(self.base/'protocol-build.json',self.receipt)
        with self.assertRaisesRegex(RuntimeError,'compile receipt'):self.verify()

    def test_packaged_rfc_vectors_must_match(self):
        (self.package/'upstream/util/vrf/vrf_test.go').write_text('// changed\n')
        with self.assertRaisesRegex(RuntimeError,'RFC vectors'):self.verify()

    def test_path_traversal_rejected(self):
        for path in ('../outside','a/../../outside','..\\outside',''):
            with self.subTest(path=path),self.assertRaises(RuntimeError):child_path(self.source,path)

    def test_empty_manifest_rejected(self):
        with self.assertRaises(RuntimeError):verify_hash_map(self.source,{})


if __name__=='__main__':unittest.main(verbosity=2)

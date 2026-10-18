"""CPU-only regressions for invalidating stale successful validation evidence."""
from pathlib import Path
import unittest
from bootstrap import temporary_directory
from validation_common import load_json,write_json
from validate_build import invalidate_validation,write_manifest_validation


class ValidationStateTests(unittest.TestCase):
    def setUp(self):
        self.context=temporary_directory('validation-state-')
        self.package=Path(self.context.__enter__())
        self.manifest={'source_sha256':{'miner/vrf.cl':'a'*64},
                       'artifact_sha256':{'tools/proxi.exe':'b'*64},
                       'validation_passed':True,'gpu_validation':{'passed':True}}
        self.report={'validation_passed':True,'gpu_validated':True,
                     'proof_checks':{'sha512':{'cases':344},
                                     'padding_boundaries':{'official_proof_checks':96}},
                     'protocol':{'accepted_improvements':4}}
        write_json(self.package/'build-manifest.json',self.manifest)
        write_json(self.package/'tools/compatibility-validation.json',self.report)

    def tearDown(self):self.context.__exit__(None,None,None)

    def test_revalidation_invalidates_both_prior_success_records_before_work(self):
        invalidate_validation(self.package)
        manifest=load_json(self.package/'build-manifest.json')
        report=load_json(self.package/'tools/compatibility-validation.json')
        self.assertFalse(manifest['validation_passed'])
        self.assertFalse(manifest['gpu_validation']['passed'])
        self.assertFalse(report['validation_passed'])
        self.assertFalse(report['gpu_validated'])
        self.assertEqual(manifest['source_sha256'],self.manifest['source_sha256'])
        self.assertEqual(manifest['artifact_sha256'],self.manifest['artifact_sha256'])

    def test_success_copies_summary_and_preserves_hash_binding(self):
        write_manifest_validation(self.package,self.report)
        manifest=load_json(self.package/'build-manifest.json')
        self.assertTrue(manifest['validation_passed'])
        self.assertEqual(manifest['gpu_validation']['sha512_cases'],344)
        self.assertEqual(manifest['gpu_validation']['padding_boundary_proofs'],96)
        self.assertEqual(manifest['gpu_validation']['accepted_improvements'],4)
        self.assertEqual(manifest['source_sha256'],self.manifest['source_sha256'])
        self.assertEqual(manifest['artifact_sha256'],self.manifest['artifact_sha256'])

    def test_either_failed_gate_clears_success_summary(self):
        for flag in ('validation_passed','gpu_validated'):
            report=dict(self.report);report[flag]=False
            write_manifest_validation(self.package,report)
            manifest=load_json(self.package/'build-manifest.json')
            self.assertFalse(manifest['validation_passed'])
            self.assertEqual(manifest['gpu_validation']['sha512_cases'],0)
            self.assertEqual(manifest['gpu_validation']['accepted_improvements'],0)


if __name__=='__main__':unittest.main()

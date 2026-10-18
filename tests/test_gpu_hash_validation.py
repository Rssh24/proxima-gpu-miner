"""CPU-only tests: fixture coverage and fail-closed GPU evidence checks."""
import copy
import hashlib
import unittest
from gpu_hash_validation import sha512_fixtures,require_optimization_checks


class HashValidationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.digest='a'*64
        self.checks={'sha512':{'passed':True,'cases':344,'lengths':list(range(114)),
                    'empty_and_abc':True,'kernel_sha256':self.digest},
                'padding_boundaries':{'passed':True,'prefix_lengths':[67,68,69],
                    'tai_message_lengths':[111,112,113],'official_proof_checks':96,
                    'nonce_carry_and_wrap':True}}

    def test_fixture_suite_includes_every_short_message_length_and_patterns(self):
        messages=sha512_fixtures()
        self.assertEqual(len(messages),344)
        self.assertEqual(messages[:2],[b'',b'abc'])
        for n in range(114):
            triple=messages[2+3*n:5+3*n]
            self.assertEqual([len(m) for m in triple],[n,n,n])
            self.assertEqual(triple[:2],[bytes(n),bytes(range(n))])
        self.assertEqual(messages,sha512_fixtures())

    def test_hashlib_reference_matches_published_sha512_known_answers(self):
        self.assertEqual(hashlib.sha512(sha512_fixtures()[0]).hexdigest(),
            'cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47'
            'd0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e')
        self.assertEqual(hashlib.sha512(sha512_fixtures()[1]).hexdigest(),
            'ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a'
            '2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f')

    def test_complete_evidence_passes(self):
        require_optimization_checks(self.checks,self.digest)

    def test_missing_new_checks_cannot_validate_old_release_evidence(self):
        with self.assertRaisesRegex(RuntimeError,'SHA512'):
            require_optimization_checks({'passed':True,'official_proof_checks':113},self.digest)

    def test_missing_or_failed_sha_boundary_rejected(self):
        for field,value in [('passed',False),('cases',343),('lengths',list(range(112))),
                            ('empty_and_abc',False),('kernel_sha256','b'*64)]:
            checks=copy.deepcopy(self.checks);checks['sha512'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(RuntimeError,'SHA512'):
                require_optimization_checks(checks,self.digest)

    def test_incomplete_vrf_padding_or_wrap_rejected(self):
        for field,value in [('passed',False),('prefix_lengths',[67]),
                            ('tai_message_lengths',[111]),('official_proof_checks',95),
                            ('nonce_carry_and_wrap',False)]:
            checks=copy.deepcopy(self.checks);checks['padding_boundaries'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(RuntimeError,'padding-boundary'):
                require_optimization_checks(checks,self.digest)


if __name__=='__main__':unittest.main()

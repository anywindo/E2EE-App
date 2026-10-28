import unittest
import os
import sys

# Add parent directory to path to import config and src modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from src import crypto
from cryptography.exceptions import InvalidTag

class TestCrypto(unittest.TestCase):
    def test_encrypt_decrypt_all_sizes(self):
        priv_a, pub_a = crypto.generate_keypair()
        priv_b, pub_b = crypto.generate_keypair()
        
        key_a = crypto.derive_shared_key(priv_a, pub_b)
        
        for size in config.MESSAGE_SIZES:
            plaintext = os.urandom(size)
            nonce, ciphertext, tag = crypto.encrypt(key_a, plaintext)
            recovered = crypto.decrypt(key_a, nonce, ciphertext, tag)
            self.assertEqual(plaintext, recovered)

    def test_different_nonces(self):
        priv_a, pub_a = crypto.generate_keypair()
        priv_b, pub_b = crypto.generate_keypair()
        key_a = crypto.derive_shared_key(priv_a, pub_b)
        
        plaintext = b"test message"
        nonce1, ciphertext1, tag1 = crypto.encrypt(key_a, plaintext)
        nonce2, ciphertext2, tag2 = crypto.encrypt(key_a, plaintext)
        
        self.assertNotEqual(nonce1, nonce2)
        # Even with same plaintext, different nonce means different ciphertext
        self.assertNotEqual(ciphertext1, ciphertext2)

    def test_tampered_ciphertext(self):
        priv_a, pub_a = crypto.generate_keypair()
        priv_b, pub_b = crypto.generate_keypair()
        key_a = crypto.derive_shared_key(priv_a, pub_b)
        
        plaintext = b"test message"
        nonce, ciphertext, tag = crypto.encrypt(key_a, plaintext)
        
        # Tamper ciphertext
        tampered_ciphertext = bytearray(ciphertext)
        if len(tampered_ciphertext) > 0:
            tampered_ciphertext[0] ^= 1
        
        with self.assertRaises(InvalidTag):
            crypto.decrypt(key_a, nonce, bytes(tampered_ciphertext), tag)
            
    def test_independent_key_pairs(self):
        priv_a, pub_a = crypto.generate_keypair()
        priv_b, pub_b = crypto.generate_keypair()
        
        key_a = crypto.derive_shared_key(priv_a, pub_b)
        key_b = crypto.derive_shared_key(priv_b, pub_a)
        
        self.assertEqual(key_a, key_b)

    def test_key_derivation_deterministic(self):
        priv_a, pub_a = crypto.generate_keypair()
        priv_b, pub_b = crypto.generate_keypair()
        
        key_a_1 = crypto.derive_shared_key(priv_a, pub_b)
        key_a_2 = crypto.derive_shared_key(priv_a, pub_b)
        
        self.assertEqual(key_a_1, key_a_2)

    def test_nist_sp_800_38d_input_validation(self):
        priv_a, pub_a = crypto.generate_keypair()
        priv_b, pub_b = crypto.generate_keypair()
        key = crypto.derive_shared_key(priv_a, pub_b)
        nonce, ciphertext, tag = crypto.encrypt(key, b"conformance test")

        # Invalid IV/nonce length (must be 12 bytes / 96 bits per SP 800-38D Sec 5.2.1.1)
        with self.assertRaises(ValueError):
            crypto.decrypt(key, b"short_nonce", ciphertext, tag)

        # Invalid tag length (must be 16 bytes / 128 bits per SP 800-38D Sec 5.2.1.2)
        with self.assertRaises(ValueError):
            crypto.decrypt(key, nonce, ciphertext, b"short_tag")

        # Invalid AES key length (must be 32 bytes / 256 bits per FIPS 197)
        with self.assertRaises(ValueError):
            crypto.encrypt(b"invalid_16b_key!", b"test")

        # Verify invocation counter tracks by hash(key) without storing raw key bytes (SP 800-38D Sec 8.3 & SP 800-56C Sec 8.4)
        self.assertGreaterEqual(crypto.get_key_invocation_count(key), 1)
        self.assertNotIn(key, crypto._KEY_INVOCATION_COUNTS)

if __name__ == '__main__':
    unittest.main()

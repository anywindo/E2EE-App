import unittest
import os
import sys
import struct

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from src import crypto
from src import protocol

class TestProtocol(unittest.TestCase):
    def test_package_unpackage(self):
        nonce = os.urandom(config.NONCE_SIZE)
        tag = os.urandom(config.TAG_SIZE)
        ciphertext = os.urandom(100)
        
        packaged = protocol.package(nonce, ciphertext, tag)
        payload = packaged[config.LENGTH_PREFIX_SIZE:] # Strip length prefix
        
        r_nonce, r_ciphertext, r_tag = protocol.unpackage(payload)
        
        self.assertEqual(nonce, r_nonce)
        self.assertEqual(ciphertext, r_ciphertext)
        self.assertEqual(tag, r_tag)
        
    def test_length_prefix(self):
        nonce = os.urandom(config.NONCE_SIZE)
        tag = os.urandom(config.TAG_SIZE)
        ciphertext = os.urandom(100)
        
        packaged = protocol.package(nonce, ciphertext, tag)
        
        prefix = packaged[:config.LENGTH_PREFIX_SIZE]
        payload = packaged[config.LENGTH_PREFIX_SIZE:]
        
        expected_length = len(payload)
        actual_length = struct.unpack(">I", prefix)[0]
        
        self.assertEqual(expected_length, actual_length)
        
    def test_public_key_serialization(self):
        priv, pub = crypto.generate_keypair()
        
        serialized = protocol.serialize_public_key(pub)
        self.assertEqual(len(serialized), config.ECDH_PUBLIC_KEY_SIZE)
        self.assertEqual(serialized[0], 0x04)
        deserialized_pub = protocol.deserialize_public_key(serialized)
        
        # Compare encoded points to check equality
        self.assertEqual(
            protocol.serialize_public_key(pub),
            protocol.serialize_public_key(deserialized_pub)
        )

    def test_invalid_public_key_rejected(self):
        with self.assertRaises(ValueError):
            protocol.deserialize_public_key(b"\x04" + b"\x00" * 30)

if __name__ == '__main__':
    unittest.main()

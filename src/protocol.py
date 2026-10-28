"""
Binary wire framing and public-key serialization protocol.

Conforms to:
- NIST SP 800-56A Rev. 3 Section 5.6.2 & Appendix C: Public-Key Representation & Validation
- NIST SP 800-38D Section 5.2.1.2: Authenticated Encryption Output (IV || Ciphertext || Tag)
- IETF RFC 2544 Section 10: Verifying Received Frames (expected frame/payload length verification)
"""

import struct
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import config

def package(nonce, ciphertext, tag):
    """
    Packages 12-byte nonce (IV), variable-length ciphertext, and 16-byte authentication tag
    with a 4-byte unsigned big-endian length prefix (Decision 12).
    Length prefix covers the entire payload length (len(nonce) + len(ciphertext) + len(tag)).
    """
    payload = nonce + ciphertext + tag
    # 4-byte big-endian payload length (NIST SP 800-56A Rev. 3 Section 3.1 Big-endian convention)
    length_prefix = struct.pack(">I", len(payload))
    return length_prefix + payload

def unpackage(data):
    """
    Unpackages payload data into (nonce, ciphertext, tag).
    Note: 'data' is the frame payload *without* the 4-byte length prefix.
    Verifies minimum frame length (nonce_size + tag_size) per NIST SP 800-38D Section 7.2 Step 1
    and IETF RFC 2544 Section 10.
    """
    nonce_size = config.NONCE_SIZE
    tag_size = config.TAG_SIZE
    
    if len(data) < nonce_size + tag_size:
        raise ValueError("Data too short")
        
    nonce = data[:nonce_size]
    tag = data[-tag_size:]
    ciphertext = data[nonce_size:-tag_size]
    
    return nonce, ciphertext, tag

def serialize_public_key(public_key):
    """
    Serializes an NIST P-256 (SECP256R1) public key to a 65-byte ANSI X9.62 uncompressed point
    (0x04 || X || Y) for wire transmission (NIST SP 800-56A Rev. 3 Appendix C).
    """
    return public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )

def deserialize_public_key(data):
    """
    Deserializes and validates an NIST P-256 (SECP256R1) public key from ANSI X9.62 uncompressed point bytes.
    Performs public-key validation (verifying point format, non-infinity, field bounds, and curve equation)
    as required by NIST SP 800-56A Rev. 3 Section 5.6.2.3.
    """
    if not isinstance(data, (bytes, bytearray)) or len(data) != config.ECDH_PUBLIC_KEY_SIZE or data[0] != 0x04:
        raise ValueError(
            f"NIST SP 800-56A public key validation failed: expected {config.ECDH_PUBLIC_KEY_SIZE}-byte "
            "uncompressed X9.62 point starting with 0x04"
        )
    curve = ec.SECP256R1() if config.ECDH_CURVE == "SECP256R1" else None
    if curve is None:
        raise ValueError(f"Unsupported ECDH curve: {config.ECDH_CURVE}")
    return ec.EllipticCurvePublicKey.from_encoded_point(
        curve, bytes(data)
    )

def pack_ack(success: bool, decryption_time_ns: int) -> bytes:
    """Packs success flag (1 byte) and decryption time (8-byte unsigned big-endian integer) into an ACK payload."""
    flag = 1 if success else 0
    return struct.pack(">B Q", flag, decryption_time_ns)

def unpack_ack(payload: bytes):
    """Unpacks 9-byte ACK payload into (success_flag, decryption_time_ns)."""
    if len(payload) != config.ACK_PAYLOAD_SIZE:
        raise ValueError("Invalid ACK payload length")
    flag, dec_time = struct.unpack(">B Q", payload)
    return bool(flag), dec_time



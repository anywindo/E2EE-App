"""
Cryptographic engine for APPTA E2EE experimentation.

Conforms to:
- NIST FIPS 186-5 & NIST SP 800-56A Rev. 3: Ephemeral ECDH Key Establishment over Curve P-256 (SECP256R1)
- NIST SP 800-56C Rev. 2 & IETF RFC 5869: Two-Step Extract-then-Expand Key Derivation (HKDF-SHA256)
- NIST FIPS 197 (Update 1) & NIST SP 800-38D: AES-256-GCM Authenticated Encryption and Decryption
"""

import os
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import config
from src.logger import get_logger

logger = get_logger("crypto")

# Track per-key invocation counts to enforce NIST SP 800-38D Section 8.3 (<= 2^32 invocations per key).
# Keyed by Python's per-process randomized hash(key) rather than the raw key bytes, so no AES key
# material is retained in this table (NIST SP 800-56C Rev. 2 Section 8.4). A hash collision can only
# cause over-counting (i.e. the limit triggers earlier), which is the conservative failure mode.
_KEY_INVOCATION_COUNTS = {}

def _get_curve():
    """Returns the approved NIST elliptic curve instance defined in config (NIST FIPS 186-5 / SP 800-56A Appendix D)."""
    if config.ECDH_CURVE == "SECP256R1":
        return ec.SECP256R1()
    raise ValueError(f"Unsupported ECDH curve: {config.ECDH_CURVE}")

def generate_keypair():
    """
    Generates an ephemeral ECDH key pair using NIST P-256 (SECP256R1).

    Standards:
    - NIST FIPS 186-5 Appendix A.2: ECC Key Pair Generation
    - NIST SP 800-56A Rev. 3 Section 5.6.1 & Section 6.1: Ephemeral Key-Pair Generation for C(2e, 0s)
    """
    curve = _get_curve()
    private_key = ec.generate_private_key(curve)
    public_key = private_key.public_key()
    logger.debug("Generated new SECP256R1 (NIST P-256) ephemeral ECDH keypair.")
    return private_key, public_key

def derive_shared_key(private_key, peer_public_key, salt=None, info=None):
    """
    Performs ECC Cofactor Diffie-Hellman (CDH) primitive followed by Two-Step HKDF-SHA256
    (Extract-then-Expand) to derive a 256-bit AES session key.

    Standards:
    - NIST SP 800-56A Rev. 3 Section 5.7.1.2: ECC CDH Primitive (computes shared secret Z)
    - NIST SP 800-56C Rev. 2 Section 5 & IETF RFC 5869 Section 2:
      Step 1 (Extract): PRK = HMAC-SHA256(salt, Z)
      Step 2 (Expand):  OKM = HKDF-Expand(PRK, info, L=32)
    - NIST SP 800-56C Rev. 2 Section 8.4: Destruction of sensitive local shared secret Z after derivation.
      NOTE: CPython `bytes` are immutable and cannot be zeroized in place; `del` releases the only
      reference so the buffer is freed by the allocator. This is best-effort, not guaranteed erasure.
    """
    if not isinstance(peer_public_key, ec.EllipticCurvePublicKey):
        raise TypeError("peer_public_key must be an EllipticCurvePublicKey instance")
    if peer_public_key.curve.name != _get_curve().name:
        raise ValueError(f"Curve mismatch: expected {_get_curve().name}, got {peer_public_key.curve.name}")

    # SP 800-56A Rev. 3 Section 5.7.1.2: Compute raw shared secret Z (32 bytes for P-256)
    shared_secret = private_key.exchange(ec.ECDH(), peer_public_key)

    effective_salt = config.HKDF_SALT if salt is None else salt
    effective_info = config.HKDF_INFO if info is None else info
    key_length_bytes = config.AES_KEY_SIZE // 8

    try:
        # KDF: HKDF-SHA256 (Decision 10, RFC 5869 Section 2, NIST SP 800-56C Rev. 2 Section 5.1)
        derived_key = HKDF(
            algorithm=hashes.SHA256(),
            length=key_length_bytes,
            salt=effective_salt,
            info=effective_info,
        ).derive(shared_secret)
    finally:
        # SP 800-56C Rev. 2 Section 8.4: Clear local reference to raw shared secret Z
        del shared_secret

    logger.debug(f"Derived {config.AES_KEY_SIZE}-bit AES key via HKDF-SHA256 from shared secret.")
    return derived_key

def get_key_invocation_count(key: bytes) -> int:
    """Returns the number of GCM-AE invocations performed under the given key."""
    return _KEY_INVOCATION_COUNTS.get(hash(key), 0)

def encrypt(key, plaintext_bytes, associated_data=None):
    """
    Encrypts plaintext using AES-256-GCM (Algorithm 4: GCM-AE_K(IV, P, A)).
    Returns (nonce, ciphertext, tag).

    Standards:
    - NIST FIPS 197 (Update 1) Section 5.1: AES-256 Forward Cipher (CIPH_K)
    - NIST SP 800-38D Section 5.2.1 & Section 7.1: GCM Authenticated Encryption (GCM-AE)
    - NIST SP 800-38D Section 8.2.2: 96-bit (12-byte) RBG-based IV/Nonce construction
    - NIST SP 800-38D Section 8.3: Invocation limit enforcement (<= 2^32 invocations per key)
    """
    if len(key) != config.AES_KEY_SIZE // 8:
        raise ValueError(f"Invalid AES key length: expected {config.AES_KEY_SIZE // 8} bytes, got {len(key)}")
    if len(plaintext_bytes) > config.GCM_MAX_PLAINTEXT_BYTES:
        raise ValueError("Plaintext length exceeds NIST SP 800-38D Section 5.2.1.1 maximum (2^39 - 256 bits)")

    key_id = hash(key)
    invocations = _KEY_INVOCATION_COUNTS.get(key_id, 0) + 1
    if invocations > config.GCM_MAX_INVOCATIONS:
        raise RuntimeError("NIST SP 800-38D Section 8.3 violation: Key invocation limit (2^32) exceeded")
    _KEY_INVOCATION_COUNTS[key_id] = invocations

    aesgcm = AESGCM(key)
    # SP 800-38D Section 8.2.2: 96-bit direct random string from OS CSPRNG (RBG)
    nonce = os.urandom(config.NONCE_SIZE)
    # AESGCM.encrypt computes C and 128-bit authentication tag T, returning C || T
    ct_with_tag = aesgcm.encrypt(nonce, plaintext_bytes, associated_data)

    tag_size_bytes = config.TAG_SIZE
    ciphertext = ct_with_tag[:-tag_size_bytes]
    tag = ct_with_tag[-tag_size_bytes:]

    logger.debug(
        f"AES-256-GCM Encryption: {len(plaintext_bytes)}B plaintext -> "
        f"{len(ciphertext)}B ciphertext + {len(tag)}B tag (nonce: {nonce.hex()})."
    )
    return nonce, ciphertext, tag

def decrypt(key, nonce, ciphertext, tag, associated_data=None):
    """
    Decrypts ciphertext and verifies authenticity using AES-256-GCM (Algorithm 5: GCM-AD_K(IV, C, A, T)).
    Raises an exception (InvalidTag / ValueError) on authentication or parameter failure.

    Standards:
    - NIST SP 800-38D Section 5.2.2 & Section 7.2: GCM Authenticated Decryption (GCM-AD)
      Step 1: Verify supported bit lengths of IV (96 bits), C (<= 2^39 - 256 bits), and T (len(T) == t = 128 bits).
      Step 8: If T == T', return P; else return FAIL (raises InvalidTag without outputting unauthenticated plaintext).
    """
    if len(key) != config.AES_KEY_SIZE // 8:
        raise ValueError(f"Invalid AES key length: expected {config.AES_KEY_SIZE // 8} bytes, got {len(key)}")
    if len(nonce) != config.NONCE_SIZE:
        raise ValueError(f"NIST SP 800-38D Step 1 FAIL: Invalid IV/nonce length ({len(nonce)}B != {config.NONCE_SIZE}B)")
    if len(tag) != config.TAG_SIZE:
        raise ValueError(f"NIST SP 800-38D Step 1 FAIL: Invalid authentication tag length ({len(tag)}B != {config.TAG_SIZE}B)")
    if len(ciphertext) > config.GCM_MAX_PLAINTEXT_BYTES:
        raise ValueError("NIST SP 800-38D Step 1 FAIL: Ciphertext exceeds maximum supported length")

    aesgcm = AESGCM(key)
    # Reassemble ciphertext + tag for AESGCM.decrypt
    ct_with_tag = ciphertext + tag
    try:
        plaintext = aesgcm.decrypt(nonce, ct_with_tag, associated_data)
        logger.debug(f"AES-256-GCM Decryption SUCCESS: {len(ciphertext)}B ciphertext -> {len(plaintext)}B plaintext.")
        return plaintext
    except Exception as e:
        logger.error(f"AES-256-GCM Decryption FAILED: {str(e)}")
        raise

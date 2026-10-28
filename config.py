"""
Experiment configuration constants for Tugas Akhir thesis project.

Standardized against authoritative NIST, IETF, and ISO/IEC methodology specifications:
- ISO/IEC 25010:2023(E): Systems and software Quality Requirements and Evaluation (SQuaRE) - Product quality model
- NIST FIPS 186-5: Digital Signature Standard (DSS) - Elliptic Curve Domain Parameters (P-256)
- NIST SP 800-56A Rev. 3: Pair-Wise Key-Establishment Schemes Using Discrete Logarithm Cryptography
- NIST SP 800-56C Rev. 2: Key-Derivation Methods in Key-Establishment Schemes (Two-Step Extract-then-Expand)
- IETF RFC 5869: HMAC-based Extract-and-Expand Key Derivation Function (HKDF)
- NIST FIPS 197 (Update 1): Advanced Encryption Standard (AES-256)
- NIST SP 800-38D: Recommendation for Block Cipher Modes of Operation: Galois/Counter Mode (GCM)
- IETF RFC 2544: Benchmarking Methodology for Network Interconnect Devices
"""

import os

# Message sizes in bytes (RFC 2544 Section 9: >= 5 frame/payload sizes spanning min to max)
MESSAGE_SIZES = [16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576]

# Repetitions (RFC 2544 Section 26.2 mandates >= 20 repeated trials for latency reporting; default = 30)
MIN_RFC2544_LATENCY_TRIALS = 20
_env_reps = os.environ.get("EXPERIMENT_REPETITIONS")
MEASURED_RUNS = int(_env_reps) if _env_reps and _env_reps.isdigit() else 30
WARMUP_RUNS = 5

# Cryptographic parameters
# NIST FIPS 186-5 & NIST SP 800-56A Rev. 3 Appendix D (Table 24): Curve P-256 (SECP256R1), 128-bit security strength
ECDH_CURVE = "SECP256R1"
ECDH_PUBLIC_KEY_SIZE = 65  # bytes: ANSI X9.62 uncompressed point (0x04 || X (32B) || Y (32B))

# NIST SP 800-56C Rev. 2 Section 5 & IETF RFC 5869 Section 2: Two-Step HKDF-SHA256
KDF_ALGORITHM = "HKDF-SHA256"
HKDF_HASH_LEN = 32  # bytes (256-bit output block of SHA-256)
# Per RFC 5869 Section 2.2 & SP 800-56C Rev. 2 Section 5.1: default salt is HashLen zero octets when None
HKDF_SALT = None
# Per RFC 5869 Section 3.2 & SP 800-56C Rev. 2 Section 5.1: FixedInfo / context-specific application info
HKDF_INFO = b"handshake data"

# NIST FIPS 197 (Update 1) Section 5 & NIST SP 800-38D Section 5.1: AES-256 (Nk=8, Nb=4, Nr=14)
AES_KEY_SIZE = 256          # bits (32 bytes)
AES_BLOCK_SIZE_BITS = 128   # bits (16 bytes)

# NIST SP 800-38D Section 5.2.1.1 & Section 8.2.2: 96-bit (12-byte) RBG-based IV/Nonce
NONCE_SIZE = 12             # bytes (96 bits recommended by SP 800-38D Sec 5.2.1.1)
# NIST SP 800-38D Section 5.2.1.2: 128-bit (16-byte) Authentication Tag (t = 128)
TAG_SIZE = 16               # bytes (128 bits)
# NIST SP 800-38D Section 5.2.1.1: Maximum plaintext length (2^39 - 256 bits = 68,719,476,704 bytes)
GCM_MAX_PLAINTEXT_BYTES = (1 << 36) - 32
# NIST SP 800-38D Section 8.3: Maximum invocations per key with RBG-based IV construction (2^32)
GCM_MAX_INVOCATIONS = 1 << 32

# Protocol parameters (Decision 12)
LENGTH_PREFIX_SIZE = 4  # bytes (32-bit unsigned big-endian integer)
ACK_PAYLOAD_SIZE = 9    # bytes: 1-byte status flag + 8-byte unsigned big-endian decryption_time_ns

# CSV Dataset configuration (Decision 16)
CSV_COLUMNS = [
    "run_id",
    "message_size_bytes",
    "encryption_time_ns",
    "decryption_time_ns",
    "latency_ns",
    "throughput_bytes_per_s",
    "success",
    "timestamp_utc"
]

# Authoritative Standards Metadata for Reporting (ISO/IEC 25010, RFC 2544 & NIST Conformance)
STANDARDS_METADATA = {
    "product_quality_model": (
        "ISO/IEC 25010:2023(E) SQuaRE Product Quality Model: "
        "Clause 3.2.1 Time behaviour (encryption/decryption time, round-trip response latency, throughput), "
        "Clause 3.8.2 Scalability (workload scaling across 16 B - 1 MB message sizes), "
        "Clause 3.6.1 Confidentiality & 3.6.2 Integrity (ECDH + AES-256-GCM AEAD), "
        "Clause 3.1.2 Functional correctness & 3.5.3 Fault tolerance (tag/length verification & failed-run handling), "
        "Annex C.2 (External quality measures of dynamic computer system behaviour)"
    ),
    "key_establishment": "NIST SP 800-56A Rev. 3 (Section 6.1, Ephemeral Unified Model C(2e, 0s) ECC CDH)",
    "elliptic_curve": "NIST FIPS 186-5 / SP 800-56A Rev. 3 Appendix D (Curve P-256 / SECP256R1)",
    "key_derivation": "NIST SP 800-56C Rev. 2 (Section 5, Two-Step Extract-then-Expand) & IETF RFC 5869 (HKDF-SHA256)",
    "block_cipher": "NIST FIPS 197 Update 1 (AES-256, 128-bit block, 14 rounds)",
    "aead_mode": "NIST SP 800-38D (Galois/Counter Mode - AES-256-GCM, 96-bit RBG IV, 128-bit Tag)",
    "benchmark_methodology": (
        "Adapted from IETF RFC 2544: conforms to Sec. 9 (>=5 sizes), Sec. 10 (received-frame checks), "
        "Sec. 26.2 (>=20 trials). Deviations: latency is application round-trip (not one-way B-A at the "
        "zero-loss rate), throughput is effective payload bytes/s (not the RFC 2544 max zero-loss rate), "
        "and per-trial duration is far below the Sec. 24 60-second recommendation."
    )
}

def validate_config():
    if not all(isinstance(x, int) and 0 < x <= GCM_MAX_PLAINTEXT_BYTES for x in MESSAGE_SIZES):
        raise ValueError("Invalid configuration: All MESSAGE_SIZES must be positive integers within SP 800-38D bounds")
    if len(MESSAGE_SIZES) < 5:
        raise ValueError("Invalid configuration: RFC 2544 Section 9 requires at least 5 payload sizes")
    if not isinstance(MEASURED_RUNS, int) or MEASURED_RUNS <= 0:
        raise ValueError("Invalid configuration: MEASURED_RUNS must be a positive integer")
    if ECDH_CURVE != "SECP256R1":
        raise ValueError("Invalid configuration: ECDH_CURVE must be 'SECP256R1' (NIST P-256)")
    if AES_KEY_SIZE not in (128, 192, 256):
        raise ValueError("Invalid configuration: FIPS 197 requires AES_KEY_SIZE to be 128, 192, or 256 bits")
    if NONCE_SIZE != 12:
        raise ValueError("Invalid configuration: SP 800-38D Section 5.2.1.1 recommends a 12-byte (96-bit) IV/nonce")
    if TAG_SIZE not in (16, 15, 14, 13, 12):
        raise ValueError("Invalid configuration: SP 800-38D Section 5.2.1.2 requires tag length in {128, 120, 112, 104, 96} bits")

validate_config()

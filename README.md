# Tugas Akhir - Thesis Experimental Instrument

This repository contains the Python implementation of an experimental end-to-end encrypted (E2EE) one-to-one text messaging system. It serves as a measurement instrument to analyze the effect of message size on E2EE performance, using ECDH (`SECP256R1`) + `HKDF-SHA256` for key establishment and `AES-256-GCM` for authenticated message encryption.

## Methodology & Standards Alignment

The experimental instrument and reporting metadata (`config.py`, `src/`, `environment.json`) are standardized against:
- **ISO/IEC 25010:2023(E) (SQuaRE):** Product Quality Model — *Time behaviour* (Clause 3.2.1), *Scalability* across payload sizes (Clause 3.8.2), *Confidentiality & Integrity* (Clauses 3.6.1 & 3.6.2), *Functional correctness & Fault tolerance* (Clauses 3.1.2 & 3.5.3), and *External dynamic quality measurement* (Annex C.2).
- **NIST FIPS 186-5 & NIST SP 800-56A Rev. 3:** Ephemeral Unified Model $C(2e, 0s)$ ECDH over Curve P-256 (`SECP256R1`) with 65-byte uncompressed ANSI X9.62 point validation.
- **NIST SP 800-56C Rev. 2 & IETF RFC 5869:** Two-step Extract-then-Expand `HKDF-SHA256` key derivation.
- **NIST FIPS 197 (Update 1) & NIST SP 800-38D:** `AES-256-GCM` authenticated encryption (256-bit key, 96-bit RBG nonce, 128-bit tag, $\le 2^{32}$ invocation limit per key).
- **IETF RFC 2544:** Adapted benchmarking methodology ($\ge 5$ payload sizes from `16 B` to `1 MB`, $\ge 20$ trials per size, received-frame verification, and DUT environment reporting). See `.agents/docs/06_final_decisions.md` for full decision traceability and documented RFC 2544 adaptations.

## Requirements

- Python 3.9+
- Dependencies listed in `requirements.txt`

## Setup

It is recommended to use a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
pip install -r requirements.txt
```

## Running the Automated End-to-End Experiment & Tests

```bash
# Run the automated end-to-end benchmark, analysis, and environment profiling
python run_e2e.py

# Run the unit test suite (19 tests)
python -m unittest discover tests -v
```

## Running Sender and Receiver Separately (LAN / Two Machines)

The experiment can also be executed across two separate machines on a local area network (LAN):

1.  **Start the receiver:**
    ```bash
    python receiver.py
    ```

2.  **Start the sender:**
    ```bash
    python sender.py
    ```

The sender will connect to the receiver, perform the ECDH key exchange, and automatically run the benchmark across predefined message sizes. Results will be saved to a CSV file.

## Running the Desktop Application (Electron)

You can launch the integrated desktop interface wrapping both Gradio apps with seamless switching:

```bash
# Install Node dependencies (first time only)
npm install

# Launch the Electron app
npm start
```

### Features
- **Dual-App Switcher**: Instantly switch between the **Benchmark & Analysis Suite** (`app.py`) and the **Interactive E2EE Chat Demo** (`chat_demo.py`).
- **Automatic Lifecycle Management**: Automatically detects your virtual environment (`venv`), boots the Python backend, waits for HTTP readiness, and cleans up processes when quitting.
- **Console Drawer**: Live streaming terminal logs for monitoring Python execution and debugging.
- **Native Shortcuts**: `CmdOrCtrl+1` for Benchmark Suite, `CmdOrCtrl+2` for Chat Demo, `CmdOrCtrl+Shift+R` to restart backend.

"""
Benchmark orchestration runner for the APPTA E2EE experimental instrument.

Methodology adapted from IETF RFC 2544:
- Sec. 9: payload size progression across 9 logarithmic sizes (16B to 1MB)  [conforms]
- Sec. 10: verifying received frames & authentication status                [conforms]
- Sec. 26.2: >= 20 measured trials per size (default 30)                     [conforms]
- Sec. 23: pre-trial priming phase -> analogous to discarded warm-up runs    [analogous]
- Sec. 24: >= 60 s per trial                                                  [deviation: per-message trials]
- Sec. 26.1/26.2 throughput & latency definitions                             [deviation: see src/timing.py]
Cryptography: NIST SP 800-38D Section 7.1 & Section 8.3 per-message AES-256-GCM.
"""

import os
import random
import uuid
import datetime
import config
from src import crypto
from src import protocol
from src.timing import Timer, calculate_throughput
from src.data import DataWriter
from src.logger import get_logger
from src.i18n import _

logger = get_logger("benchmark")

def generate_plaintext(size_bytes):
    """Generates cryptographically random test payload of the specified byte length."""
    return os.urandom(size_bytes)

def format_size_short(size_bytes: int) -> str:
    """Formats payload size into compact string (e.g. 64 KB, 1 MB, 16 B)."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes // (1024 * 1024)} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes // 1024} KB"
    else:
        return f"{size_bytes} B"

def format_size_label(size_bytes: int) -> str:
    """Formats payload size into clean human-readable representation."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes // (1024 * 1024)} MB ({size_bytes:,} B)"
    elif size_bytes >= 1024:
        return f"{size_bytes // 1024} KB ({size_bytes:,} B)"
    else:
        return f"{size_bytes} B"

def format_throughput_label(bytes_per_sec: float) -> str:
    """Formats throughput into human-friendly scaled rate (MB/s or KB/s)."""
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):>6.2f} MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:>6.2f} KB/s"
    else:
        return f"{bytes_per_sec:>6.2f} B/s"

class BenchmarkRunner:
    def __init__(self, sender, data_writer=None):
        self.sender = sender
        self.data_writer = data_writer if data_writer else DataWriter()
        
    def run_experiment(self):
        # Create execution plan: randomize the order of message sizes (Decision 15)
        plan = list(config.MESSAGE_SIZES)
        random.shuffle(plan)
        
        if config.MEASURED_RUNS < config.MIN_RFC2544_LATENCY_TRIALS:
            logger.warning(
                f"RFC 2544 Section 26.2 recommends at least {config.MIN_RFC2544_LATENCY_TRIALS} "
                f"measured trials per payload size (current MEASURED_RUNS={config.MEASURED_RUNS})."
            )
            
        total_runs = len(plan) * config.MEASURED_RUNS
        current_run = 0
        
        experiment_start = datetime.datetime.now()
        
        plan_labels = [format_size_short(s) for s in plan]
        logger.info(_("starting_exp", sizes=len(plan), runs=config.MEASURED_RUNS, warmups=config.WARMUP_RUNS))
        logger.info(_("exec_order", plan=", ".join(plan_labels)))
        
        for size_idx, size in enumerate(plan, start=1):
            print("", flush=True)
            size_lbl = format_size_label(size)
            logger.info(_("msg_size", size_label=size_lbl, idx=size_idx, total_sizes=len(plan)))
            # Generate random plaintext for this size run (RFC 2544 Section 9)
            plaintext = generate_plaintext(size)
            
            # Warm-up runs (Decision 13: discarded prior to CSV recording)
            logger.info(_("warmup_phase_start", warmups=config.WARMUP_RUNS))
            for w in range(config.WARMUP_RUNS):
                w_ok, w_enc_ns, w_dec_ns, w_lat_ns, w_thr = self._execute_single_run(plaintext, record=False)
                logger.info(
                    _(
                        "warmup_trial_log",
                        w=w + 1,
                        warmups=config.WARMUP_RUNS,
                        status="OK" if w_ok else "FAIL",
                        enc_ms=w_enc_ns / 1_000_000.0,
                        dec_ms=w_dec_ns / 1_000_000.0,
                        lat_ms=w_lat_ns / 1_000_000.0,
                    )
                )
                
            # Measured runs (Decision 7 & RFC 2544 Section 26.2: repeated trials per payload size)
            logger.info(_("measured_phase_start", runs=config.MEASURED_RUNS))
            for m in range(config.MEASURED_RUNS):
                current_run += 1
                success, enc_ns, dec_ns, lat_ns, throughput = self._execute_single_run(plaintext, record=True)
                thr_str = format_throughput_label(throughput)
                logger.info(
                    _(
                        "measured_trial_log",
                        m=m + 1,
                        runs=config.MEASURED_RUNS,
                        current=current_run,
                        total=total_runs,
                        status="OK" if success else "FAIL",
                        enc_ms=enc_ns / 1_000_000.0,
                        dec_ms=dec_ns / 1_000_000.0,
                        lat_ms=lat_ns / 1_000_000.0,
                        thr_str=thr_str,
                    )
                )
                    
        experiment_end = datetime.datetime.now()
        duration = experiment_end - experiment_start
        
        # Signal receiver to stop (sending an authenticated 0-byte message)
        empty_nonce, empty_ciphertext, empty_tag = crypto.encrypt(self.sender.session_key, b"")
        self.sender.send_message(protocol.package(empty_nonce, empty_ciphertext, empty_tag))
        
        print("", flush=True)
        logger.info(_("exp_complete"))
        logger.info(_("total_time", duration=duration))
        if self.data_writer:
            logger.info(_("results_saved", filename=self.data_writer.filename))
            self.data_writer.close()
            
    def _execute_single_run(self, plaintext, record=True):
        run_id = str(uuid.uuid4())
        
        try:
            # Decision 4: Application Round-Trip Latency (adapted from, not identical to, RFC 2544 Sec. 26.2)
            with Timer() as total_timer:
                # Decision 2: Encryption Timing Boundary (Nonce generation + AES-GCM encryption + Packaging)
                with Timer() as enc_timer:
                    nonce, ciphertext, tag = crypto.encrypt(self.sender.session_key, plaintext)
                    packaged_data = protocol.package(nonce, ciphertext, tag)
                
                self.sender.send_message(packaged_data)
                ack = self.sender.receive_ack()
                
            latency_ns = total_timer.elapsed_ns
            encryption_time_ns = enc_timer.elapsed_ns
            
            success, decryption_time_ns = protocol.unpack_ack(ack)
            # Decision 5: Effective End-to-End Throughput in bytes/s (not RFC 2544 Sec. 26.1 zero-loss rate)
            throughput = calculate_throughput(len(plaintext), latency_ns)
            
            if record and self.data_writer:
                self.data_writer.write_row(
                    run_id=run_id,
                    message_size_bytes=len(plaintext),
                    encryption_time_ns=encryption_time_ns,
                    decryption_time_ns=decryption_time_ns,
                    latency_ns=latency_ns,
                    throughput_bytes_per_s=throughput,
                    success=success
                )
            return success, encryption_time_ns, decryption_time_ns, latency_ns, throughput
        except Exception as e:
            logger.error(_("err_run", e=e))
            if record and self.data_writer:
                self.data_writer.write_row(
                    run_id=run_id,
                    message_size_bytes=len(plaintext),
                    encryption_time_ns=0,
                    decryption_time_ns=0,
                    latency_ns=0,
                    throughput_bytes_per_s=0.0,
                    success=False
                )
            return False, 0, 0, 0, 0.0

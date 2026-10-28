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
        
        logger.info(_("starting_exp", sizes=len(plan), runs=config.MEASURED_RUNS, warmups=config.WARMUP_RUNS))
        logger.info(_("exec_order", plan=plan))
        
        for size in plan:
            logger.info(_("msg_size", size=size))
            # Generate random plaintext for this size run (RFC 2544 Section 9)
            plaintext = generate_plaintext(size)
            
            # Warm-up runs (Decision 13: discarded prior to CSV recording)
            for w in range(config.WARMUP_RUNS):
                self._execute_single_run(plaintext, record=False)
                
            # Measured runs (Decision 7 & RFC 2544 Section 26.2: repeated trials per payload size)
            for m in range(config.MEASURED_RUNS):
                current_run += 1
                success = self._execute_single_run(plaintext, record=True)
                
                # Progress
                if m % 10 == 0 or m == config.MEASURED_RUNS - 1:
                    logger.debug(f"  [{current_run}/{total_runs}] Run {m+1}/{config.MEASURED_RUNS} " + ("OK" if success else "FAIL"))
                    
        experiment_end = datetime.datetime.now()
        duration = experiment_end - experiment_start
        
        # Signal receiver to stop (sending an authenticated 0-byte message)
        empty_nonce, empty_ciphertext, empty_tag = crypto.encrypt(self.sender.session_key, b"")
        self.sender.send_message(protocol.package(empty_nonce, empty_ciphertext, empty_tag))
        
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
            return success
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
            return False

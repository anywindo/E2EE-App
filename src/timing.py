"""
High-resolution monotonic timing and throughput calculation primitives.

Standardized Quality & Benchmarking Alignment:
- ISO/IEC 25010:2023(E) Clause 3.2.1 (Performance efficiency -> Time behaviour) & Annex C.2:
  External dynamic quality measures quantifying processing/response times (`encryption_time_ns`,
  `decryption_time_ns`, `latency_ns`) and throughput rate (`throughput_bytes_per_s`) under
  specified conditions.
- Relation to IETF RFC 2544 (adapted, not conformant):
  - Latency here is application round-trip (Decision 4), not RFC 2544 Sec. 26.2 one-way latency
    (Timestamp B - Timestamp A measured at the zero-loss throughput rate).
  - Throughput here is effective payload bytes/s (Decision 5), not RFC 2544 Sec. 26.1 throughput
    (maximum frame rate with zero frame loss).
See Methodological Decisions #2, #3, #4, and #5 (.agents/docs/06_final_decisions.md).
"""

import time

class Timer:
    """Context-manager timer using monotonic nanosecond clock (`time.perf_counter_ns`)."""
    def __init__(self):
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = time.perf_counter_ns()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter_ns()

    @property
    def elapsed_ns(self):
        if self.start_time is None or self.end_time is None:
            raise ValueError("Timer has not completed")
        return self.end_time - self.start_time

def calculate_throughput(message_size_bytes, latency_ns):
    """
    Calculates effective end-to-end throughput in bytes per second (Decision 5).
    NOTE: this is NOT RFC 2544 Sec. 26.1 throughput (max zero-loss rate); it is payload bytes
    divided by one application round-trip.
    """
    if latency_ns == 0:
        return 0.0
    latency_s = latency_ns / 1_000_000_000.0
    return message_size_bytes / latency_s

"""
Receiver node for the APPTA E2EE benchmarking instrument.

Conforms to:
- NIST SP 800-56A Rev. 3 & SP 800-56C Rev. 2: Session-level Ephemeral ECDH + HKDF-SHA256 Handshake
- NIST SP 800-38D Section 7.2: GCM Authenticated Decryption (GCM-AD) and Tag Verification
- IETF RFC 2544 Section 10: Verifying Received Frames (expected frame/payload length check)
"""

import sys
import socket
import config
from src.network import Receiver
from src.i18n import _
from src import crypto
from src import protocol
from src.timing import Timer
from src.logger import get_logger

logger = get_logger("receiver")

def main():
    host = '127.0.0.1'
    port = 5000
    
    receiver = Receiver(host, port)
    logger.info(f"Starting receiver on {host}:{port}...")
    try:
        receiver.start()
        logger.info(_("receiver_sender_connected"))
        receiver.handshake()
        logger.info(
            f"ECDH+HKDF Handshake complete in {receiver.handshake_time_ns / 1_000_000:.3f} ms "
            f"({receiver.handshake_time_ns} ns). Waiting for messages..."
        )
        
        messages_received = 0
        
        while True:
            payload = receiver.receive_message()
            
            # Decision 3 Timing Boundary: Starts immediately before parsing received ciphertext package;
            # ends immediately after plaintext recovery and verification.
            with Timer() as dec_timer:
                try:
                    # Parsing is inside the try so a malformed frame is recorded as a failed trial
                    # instead of aborting the receiver loop (IETF RFC 2544 Section 10).
                    nonce, ciphertext, tag = protocol.unpackage(payload)
                    # NIST SP 800-38D Section 7.2 (Algorithm 5): GCM-AD verifies tag T == T'
                    # and raises InvalidTag if tampered. Successful tag verification is the
                    # integrity check on the recovered plaintext (forgery probability <= 2^-128).
                    plaintext = crypto.decrypt(receiver.session_key, nonce, ciphertext, tag)
                    # IETF RFC 2544 Section 10: sanity-check recovered length against the frame.
                    # Redundant by construction (SP 800-38D Sec. 5.2.1.2: len(P) == len(C)), kept as
                    # a defensive check; it does NOT compare against the sender's original bytes.
                    success = (len(plaintext) == len(ciphertext))
                except Exception as e:
                    success = False
                    plaintext = b""
            
            if len(plaintext) == 0 and success:
                # 0-byte authenticated plaintext is the STOP signal
                logger.info(f"Received STOP signal. Total messages processed: {messages_received}")
                break
                
            decryption_time_ns = dec_timer.elapsed_ns
            
            ack_payload = protocol.pack_ack(success, decryption_time_ns)
            receiver.send_ack(ack_payload)
            messages_received += 1
            
    except socket.timeout:
        logger.warning("Receiver timeout reached. Graceful shutdown.")
    except ConnectionError:
        logger.warning(f"Connection lost mid-experiment. Graceful shutdown, partial results valid. Processed: {messages_received}")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        receiver.close()

if __name__ == "__main__":
    main()

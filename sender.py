import sys
from src.network import Sender
from src.i18n import _
from src.benchmark import BenchmarkRunner
from src.logger import get_logger

logger = get_logger("sender")

def main():
    host = '127.0.0.1'
    port = 5000
    
    sender = Sender(host, port)
    logger.info(f"Connecting to receiver on {host}:{port}...")
    try:
        sender.connect()
        logger.info(_("sender_connected"))
        sender.handshake()
        logger.info(
            f"ECDH+HKDF Handshake complete in {sender.handshake_time_ns / 1_000_000:.3f} ms "
            f"({sender.handshake_time_ns} ns, isolated from per-message timing)."
        )
        
        runner = BenchmarkRunner(sender)
        runner.run_experiment()
        
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        sender.close()

if __name__ == "__main__":
    main()

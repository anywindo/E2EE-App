import subprocess
import time
import os
import sys
from src.logger import get_logger

logger = get_logger("e2e_runner")

import datetime

def main():
    start_time = time.time()
    
    # Get configuration
    repetitions = os.environ.get("EXPERIMENT_REPETITIONS", "30")
    
    config_msg = (
        "--- E2EE Benchmark Configuration ---\n"
        "ECDH Curve: SECP256R1 (NIST P-256)\n"
        "KDF Algorithm: HKDF-SHA256\n"
        "AEAD Cipher: AES-256-GCM (256-bit key, 12B nonce, 128-bit tag)\n"
        "Message Sizes: 16 B, 64 B, 256 B, 1 KB, 4 KB, 16 KB, 64 KB, 256 KB, 1 MB\n"
        f"Measured Repetitions per Size: {repetitions} (+ 5 warm-ups)\n"
        "Standards: NIST FIPS 186-5/197, SP 800-56A/56C/38D, IETF RFC 5869/2544, ISO/IEC 25010:2023\n"
        "------------------------------------"
    )
    
    logger.info("Starting E2E Validation Test...")
    logger.info("\n" + config_msg)
    tz_utc_7 = datetime.timezone(datetime.timedelta(hours=7))
    now = datetime.datetime.now(tz_utc_7).strftime('%Y%m%d_%H%M%S')
    run_folder = os.path.join("results", f"run_{now}")
    os.makedirs(run_folder, exist_ok=True)
    
    # 1. Record Environment
    logger.info("Recording Environment...")
    subprocess.run([sys.executable, "src/environment.py", os.path.join(run_folder, "environment.json")], check=True)
    
    # 2. Start Receiver
    logger.info("Starting Receiver...")
    env = os.environ.copy()
    env["E2E_RUN_FOLDER"] = run_folder
    receiver = subprocess.Popen([sys.executable, "receiver.py"], env=env)
    time.sleep(1)
    
    # 3. Start Sender
    logger.info("Starting Sender (running benchmark)...")
    sender = subprocess.run([sys.executable, "sender.py"], env=env)
    
    if sender.returncode != 0:
        logger.error("Sender failed.")
        receiver.terminate()
        sys.exit(1)
        
    receiver.wait()
    
    latest_csv = os.path.join(run_folder, "results.csv")
    if not os.path.exists(latest_csv):
        logger.error("No CSV found.")
        sys.exit(1)
    
    logger.info(f"Running Analysis on {latest_csv}...")
    subprocess.run([sys.executable, "src/analysis.py", latest_csv, "--outdir", run_folder], check=True)
    
    # Check outputs
    assert os.path.exists(os.path.join(run_folder, "plot_latency.png")), "Latency plot missing"
    assert os.path.exists(os.path.join(run_folder, "summary.csv")), "Summary CSV missing"
    
    total_time = time.time() - start_time
    logger.info("E2E Test completed successfully!")
    logger.info("\n--- Test Finished ---")
    logger.info(f"Total time taken: {total_time:.2f} seconds")
    logger.info("\n" + config_msg)

if __name__ == "__main__":
    main()

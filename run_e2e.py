import time
import os
import sys
import threading
import datetime
from src.logger import get_logger
from src import environment
from src import analysis

logger = get_logger("e2e_runner")

def run_benchmark_pipeline(repetitions=None, output_folder=None, log_callback=None):
    """
    Executes the full end-to-end benchmark in-process, supporting both
    standard CLI execution and frozen PyInstaller standalone packages.
    """
    start_time = time.time()
    
    # Lazy import to ensure config and network are ready
    from receiver import main as receiver_main
    from sender import main as sender_main
    
    if repetitions is None:
        repetitions = os.environ.get("EXPERIMENT_REPETITIONS", "30")
    else:
        os.environ["EXPERIMENT_REPETITIONS"] = str(int(repetitions))
        
    config_msg = (
        "================================================================================\n"
        "                         E2EE BENCHMARK CONFIGURATION                           \n"
        "================================================================================\n"
        "  ECDH Curve        : SECP256R1 (NIST P-256)\n"
        "  KDF Algorithm     : HKDF-SHA256\n"
        "  AEAD Cipher       : AES-256-GCM (256-bit key, 12B nonce, 128-bit tag)\n"
        "  Message Sizes     : 16 B, 64 B, 256 B, 1 KB, 4 KB, 16 KB, 64 KB, 256 KB, 1 MB\n"
        f"  Repetitions/Size  : {repetitions} measured (+ 5 warm-ups discarded)\n"
        "  Standards         : NIST FIPS 186-5/197, SP 800-56A/56C/38D,\n"
        "                      IETF RFC 5869/2544, ISO/IEC 25010:2023\n"
        "================================================================================"
    )
    
    logger.info("Starting E2E Validation Test...")
    print(config_msg, flush=True)
    if log_callback:
        log_callback(config_msg + "\n")
        
    if output_folder:
        run_folder = output_folder
    else:
        tz_utc_7 = datetime.timezone(datetime.timedelta(hours=7))
        now = datetime.datetime.now(tz_utc_7).strftime('%Y%m%d_%H%M%S')
        run_folder = os.path.join("results", f"run_{now}")
        
    os.makedirs(run_folder, exist_ok=True)
    os.environ["E2E_RUN_FOLDER"] = run_folder
    
    # 1. Record Environment
    logger.info("Recording Environment...")
    env_file = os.path.join(run_folder, "environment.json")
    environment.record_environment(env_file)
    
    # 2. Start Receiver in background thread
    logger.info("Starting Receiver...")
    receiver_thread = threading.Thread(target=receiver_main, daemon=True)
    receiver_thread.start()
    time.sleep(1)
    
    # 3. Start Sender in current thread
    logger.info("Starting Sender (running benchmark)...")
    sender_main()
    
    # Wait for receiver to finish processing STOP signal
    receiver_thread.join(timeout=5)
    
    latest_csv = os.path.join(run_folder, "results.csv")
    if not os.path.exists(latest_csv):
        logger.error("No CSV found.")
        raise FileNotFoundError(f"results.csv not found in {run_folder}")
        
    logger.info(f"Running Analysis on {latest_csv}...")
    df = analysis.load_results(latest_csv)
    summary_df = analysis.compute_aggregation(df)
    analysis.export_summary_table(summary_df, os.path.join(run_folder, "summary.csv"))
    analysis.generate_all_plots(summary_df, run_folder)
    
    # Verify outputs
    assert os.path.exists(os.path.join(run_folder, "plot_latency.png")), "Latency plot missing"
    assert os.path.exists(os.path.join(run_folder, "summary.csv")), "Summary CSV missing"
    
    total_time = time.time() - start_time
    print("", flush=True)
    done_msg = (
        "================================================================================\n"
        f"E2E Benchmark Completed Successfully in {total_time:.2f} seconds! (Output: {run_folder})\n"
        "================================================================================\n"
    )
    logger.info(done_msg)
    if log_callback:
        log_callback(done_msg)
    return run_folder

def main():
    run_benchmark_pipeline()

if __name__ == "__main__":
    main()

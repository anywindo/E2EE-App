"""
Statistical aggregation, IQR outlier filtering, and visualization pipeline.

Conforms to:
- ISO/IEC 25010:2023(E) Clause 3.2.1 (Time behaviour) & Clause 3.8.2 (Scalability):
  Evaluates how external dynamic time-behaviour measures (encryption time, decryption time,
  round-trip latency, and effective throughput) scale across growing payload workloads (16 B to 1 MB).
- ISO/IEC 25010:2023(E) Clause 3.1.2 (Functional correctness) & Clause 3.5.3 (Fault tolerance):
  Filters dataset to validated successful trials (`success == True`) per Decision 17.
- IETF RFC 2544 Section 26.2 (mean across >= 20 trials per size) and Section 4 (variance/outlier handling).
"""

import os
import sys

# Ensure persistent Matplotlib cache directory to avoid rebuilding the font cache on every app launch
if "MPLCONFIGDIR" not in os.environ:
    if sys.platform == "win32":
        base_cache = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        mpl_dir = os.path.join(base_cache, "E2EESuite", "matplotlib")
    else:
        mpl_dir = os.path.expanduser("~/.cache/e2ee_suite_matplotlib")
    os.makedirs(mpl_dir, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = mpl_dir

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import argparse

def load_results(csv_path):
    """Reads CSV and filters to successful runs only."""
    df = pd.read_csv(csv_path)
    # Ensure success column is evaluated as boolean
    if df['success'].dtype == object:
        df['success'] = df['success'].astype(str).str.lower() == 'true'
    
    return df[df['success'] == True]

def compute_aggregation(df):
    """Computes mean, median, std, min, max for each metric grouped by message size."""
    
    if not df.empty:
        cols = ["encryption_time_ns", "decryption_time_ns", "latency_ns", "throughput_bytes_per_s"]
        # Calculate Q1, Q3, and IQR per message size
        Q1 = df.groupby('message_size_bytes')[cols].transform('quantile', 0.25)
        Q3 = df.groupby('message_size_bytes')[cols].transform('quantile', 0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        # Keep rows where ALL metrics are within bounds
        mask = ((df[cols] >= lower_bound) & (df[cols] <= upper_bound)).all(axis=1)
        df = df[mask].copy()

    metrics = [
        "encryption_time_ns",
        "decryption_time_ns",
        "latency_ns",
        "throughput_bytes_per_s"
    ]
    
    agg_funcs = ['mean', 'median', 'std', 'min', 'max']
    # Build dictionary for aggregation
    agg_dict = {metric: agg_funcs for metric in metrics}
    
    # Group by message size
    grouped = df.groupby('message_size_bytes').agg(agg_dict)
    
    # Flatten multi-level columns
    grouped.columns = ['_'.join(col).strip() for col in grouped.columns.values]
    grouped = grouped.reset_index()
    
    # Fill NaN for std in case there's only 1 run (std is NaN)
    grouped = grouped.fillna(0)
    
    # Sort by message size to ensure plots and tables are ordered
    grouped = grouped.sort_values('message_size_bytes').reset_index(drop=True)
    
    # Add converted columns for plotting
    for agg in agg_funcs:
        grouped[f"encryption_time_ms_{agg}"] = grouped[f"encryption_time_ns_{agg}"] / 1_000_000
        grouped[f"decryption_time_ms_{agg}"] = grouped[f"decryption_time_ns_{agg}"] / 1_000_000
        grouped[f"latency_ms_{agg}"] = grouped[f"latency_ns_{agg}"] / 1_000_000
        grouped[f"throughput_KB_s_{agg}"] = grouped[f"throughput_bytes_per_s_{agg}"] / 1024
        
    return grouped

def export_summary_table(aggregated, output_path):
    """Exports the aggregated stats to a CSV file."""
    aggregated.to_csv(output_path, index=False)

def plot_metric_vs_size(aggregated_df, metric_base_name, y_label, title, output_path):
    """Generates a log-x scale plot for a given metric using median and std deviation."""
    x = aggregated_df['message_size_bytes']
    y = aggregated_df[f"{metric_base_name}_median"]
    yerr = aggregated_df[f"{metric_base_name}_std"]
    
    plt.figure(figsize=(10, 6))
    
    # Plot line with error bars
    plt.errorbar(x, y, yerr=yerr, fmt='o-', capsize=5, capthick=1.5, markersize=6, 
                 label='Median \u00b1 Std Dev', color='#1f77b4', ecolor='#ff7f0e')
    
    plt.xscale('log', base=2)
    
    # Customize x-axis ticks to show human-readable sizes (optional, but requested)
    # Let's rely on standard log formatting for simplicity, or set explicit ticks
    plt.xticks(x, [str(int(sz)) for sz in x], rotation=45)
    
    plt.xlabel('Message Size (Bytes)')
    plt.ylabel(y_label)
    plt.title(title)
    plt.grid(True, which="both", ls="--", alpha=0.6)
    plt.legend()
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, format='png')
    plt.close()

def generate_all_plots(aggregated_df, output_dir):
    """Generates all four required plots into the output directory."""
    os.makedirs(output_dir, exist_ok=True)
    
    plots_config = [
        {
            "metric": "encryption_time_ms",
            "y_label": "Time (ms)",
            "title": "Encryption Time vs Message Size (ms)",
            "filename": "plot_encryption_time.png"
        },
        {
            "metric": "encryption_time_ns",
            "y_label": "Time (nanoseconds)",
            "title": "Encryption Time vs Message Size (ns)",
            "filename": "plot_encryption_time_ns.png"
        },
        {
            "metric": "decryption_time_ms",
            "y_label": "Time (ms)",
            "title": "Decryption Time vs Message Size (ms)",
            "filename": "plot_decryption_time.png"
        },
        {
            "metric": "decryption_time_ns",
            "y_label": "Time (nanoseconds)",
            "title": "Decryption Time vs Message Size (ns)",
            "filename": "plot_decryption_time_ns.png"
        },
        {
            "metric": "latency_ms",
            "y_label": "Latency (ms)",
            "title": "End-to-End Latency vs Message Size (ms)",
            "filename": "plot_latency.png"
        },
        {
            "metric": "latency_ns",
            "y_label": "Latency (nanoseconds)",
            "title": "End-to-End Latency vs Message Size (ns)",
            "filename": "plot_latency_ns.png"
        },
        {
            "metric": "throughput_KB_s",
            "y_label": "Throughput (KB/s)",
            "title": "Throughput vs Message Size (KB/s)",
            "filename": "plot_throughput.png"
        },
        {
            "metric": "throughput_bytes_per_s",
            "y_label": "Throughput (Bytes/s)",
            "title": "Throughput vs Message Size (Bytes/s)",
            "filename": "plot_throughput_bytes.png"
        }
    ]
    
    for cfg in plots_config:
        out_path = os.path.join(output_dir, cfg["filename"])
        plot_metric_vs_size(
            aggregated_df, 
            cfg["metric"], 
            cfg["y_label"], 
            cfg["title"], 
            out_path
        )

def main():
    parser = argparse.ArgumentParser(description="Analyze Tugas Akhir benchmark results")
    parser.add_argument("csv_path", help="Path to raw benchmark CSV file")
    parser.add_argument("--outdir", default="results", help="Directory to save plots and summary")
    
    args = parser.parse_args()
    
    print(f"Loading data from {args.csv_path}...")
    df = load_results(args.csv_path)
    print(f"Loaded {len(df)} successful runs.")
    
    agg = compute_aggregation(df)
    
    os.makedirs(args.outdir, exist_ok=True)
    
    # Export summary
    base_name = os.path.basename(args.csv_path)
    if base_name == "results.csv":
        summary_name = "summary.csv"
    elif base_name.startswith("results_"):
        summary_name = base_name.replace("results_", "summary_", 1)
    else:
        summary_name = f"summary_{base_name}"
        
    summary_path = os.path.join(args.outdir, summary_name)
    export_summary_table(agg, summary_path)
    print(f"Exported summary to {summary_path}")
    
    print("Generating plots...")
    generate_all_plots(agg, args.outdir)
    print(f"Plots saved to {args.outdir}/ directory.")

if __name__ == "__main__":
    main()

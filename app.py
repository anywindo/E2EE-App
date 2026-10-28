import gradio as gr
import subprocess
from src.i18n import _, set_saved_language, CURRENT_LANG
import sys
import os
import glob
import pandas as pd
import time
import json
import plotly.graph_objects as go

LABEL_MAP = {
    "message_size_bytes": "Message Size (Bytes)",
    "encryption_time_ms": "Encryption Time (ms)",
    "decryption_time_ms": "Decryption Time (ms)",
    "latency_ms": "Latency (ms)",
    "throughput_KB_s": "Throughput (KB/s)",
    "encryption_time_ns": "Encryption Time (ns)",
    "decryption_time_ns": "Decryption Time (ns)",
    "latency_ns": "Latency (ns)",
    "throughput_bytes_per_s": "Throughput (Bytes/s)"
}

def plot_plotly(df, x_col, y_metric, title=None, y_label=None):
    if df is None or df.empty:
        return go.Figure()
    
    # Resolve X
    if x_col in df.columns:
        x = df[x_col]
    elif f"{x_col}_median" in df.columns:
        x = df[f"{x_col}_median"]
    else:
        return go.Figure()

    # Resolve Y
    if f"{y_metric}_median" in df.columns:
        y = df[f"{y_metric}_median"]
        if f"{y_metric}_std" in df.columns:
            yerr = df[f"{y_metric}_std"]
        else:
            yerr = None
    elif y_metric in df.columns:
        y = df[y_metric]
        yerr = None
    else:
        return go.Figure()
        
    if not title:
        title = f"{LABEL_MAP.get(y_metric, y_metric)} vs {LABEL_MAP.get(x_col, x_col)}"
    if not y_label:
        y_label = LABEL_MAP.get(y_metric, y_metric)

    fig = go.Figure()
    
    error_y = None
    if yerr is not None:
        error_y = dict(type='data', array=yerr, visible=True, color='#ff7f0e', thickness=1.5)
        
    fig.add_trace(go.Scatter(
        x=x, y=y,
        error_y=error_y,
        mode='lines+markers',
        name='Median ± Std Dev' if yerr is not None else 'Value',
        line=dict(color='#1f77b4'),
        marker=dict(color='#1f77b4', size=6)
    ))
    
    xaxis_kwargs = dict(title=LABEL_MAP.get(x_col, x_col))
    if x_col == 'message_size_bytes':
        xaxis_kwargs.update(
            type='log',
            tickmode='array',
            tickvals=x.tolist(),
            ticktext=[str(int(val)) for val in x]
        )
    
    fig.update_layout(
        title=title,
        xaxis_title=LABEL_MAP.get(x_col, x_col),
        yaxis_title=y_label,
        xaxis=xaxis_kwargs,
        template="plotly_white"
    )
    return fig

def update_all_plots(df, x1, y1, x2, y2, x3, y3, x4, y4):
    if df is None or df.empty:
        return go.Figure(), go.Figure(), go.Figure(), go.Figure()
    p1 = plot_plotly(df, x1, y1)
    p2 = plot_plotly(df, x2, y2)
    p3 = plot_plotly(df, x3, y3)
    p4 = plot_plotly(df, x4, y4)
    return p1, p2, p3, p4




def format_df_headers(df, translate=True):
    if df.empty or not translate:
        return df
    
    new_cols = []
    for col in df.columns:
        if col in LABEL_MAP:
            new_cols.append(LABEL_MAP[col])
        else:
            base_col = col.replace("_median", "").replace("_std", "")
            if base_col in LABEL_MAP:
                suffix = " (Median)" if "_median" in col else " (Std Dev)" if "_std" in col else ""
                new_cols.append(LABEL_MAP[base_col] + suffix)
            else:
                new_cols.append(col.replace("_", " ").title())
    
    df_copy = df.copy()
    df_copy.columns = new_cols
    return df_copy

def run_experiment(repetitions, translate_headers, x1, y1, x2, y2, x3, y3, x4, y4):
    # Set the environment variable
    env = os.environ.copy()
    env["EXPERIMENT_REPETITIONS"] = str(int(repetitions))
    
    # Run the experiment as a subprocess
    process = subprocess.Popen(
        [sys.executable, "run_e2e.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1 # Line buffered
    )
    
    log_output = ""
    for line in iter(process.stdout.readline, ''):
        log_output += line
        # Yield partial updates for the live log, and gr.update() to keep other components unchanged
        yield (
            gr.update(value=log_output, autoscroll=True), 
            gr.update(interactive=False), # keep button disabled
            gr.update(), gr.update(), gr.update(),
            gr.update(), gr.update(), gr.update(), gr.update(), 
            gr.update(), gr.update(), gr.update()
        )
    
    process.stdout.close()
    return_code = process.wait()
    
    if return_code != 0:
        log_output += f"\n\nExperiment failed with exit code {return_code}."
        yield (
            gr.update(value=log_output, autoscroll=False), 
            gr.update(interactive=True), # re-enable button
            gr.update(), gr.update(), gr.update(),
            gr.update(), gr.update(), gr.update(), gr.update(), 
            gr.update(), gr.update(), gr.update()
        )
        return

    log_output += "\n\nExperiment completed successfully! Loading results..."
    
    # Find the newest run folder
    results_dir = "results"
    try:
        run_folders = [os.path.join(results_dir, d) for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))]
        latest_folder = max(run_folders, key=os.path.getmtime)
    except Exception as e:
        log_output += f"\nError locating results: {e}"
        yield (
            gr.update(value=log_output, autoscroll=False), 
            gr.update(interactive=True), 
            gr.update(), gr.update(), gr.update(),
            gr.update(), gr.update(), gr.update(), gr.update(), 
            gr.update(), gr.update(), gr.update()
        )
        return
    
    summary_csv = os.path.join(latest_folder, "summary.csv")
    results_csv = os.path.join(latest_folder, "results.csv")
    env_json = os.path.join(latest_folder, "environment.json")
    
    try:
        summary_df = pd.read_csv(summary_csv)
    except Exception:
        summary_df = pd.DataFrame()
        
    try:
        results_df = pd.read_csv(results_csv)
    except Exception:
        results_df = pd.DataFrame()
        
    try:
        with open(env_json, "r") as f:
            env_data = json.load(f)
            env_df = pd.DataFrame(list(env_data.items()), columns=["Property", "Value"])
            env_df["Property"] = env_df["Property"].str.replace("_", " ").str.title()
    except Exception:
        env_df = pd.DataFrame(columns=["Property", "Value"])

    fig_enc, fig_dec, fig_lat, fig_thr = update_all_plots(summary_df, x1, y1, x2, y2, x3, y3, x4, y4)
    
    # Yield final successful state
    yield (
        gr.update(value=log_output, autoscroll=False), 
        gr.update(interactive=True), 
        summary_df, format_df_headers(summary_df, translate_headers), summary_csv, 
        fig_enc, fig_dec, fig_lat, fig_thr, 
        format_df_headers(results_df, translate_headers), results_csv, env_df
    )

def get_run_folders():
    results_dir = "results"
    try:
        folders = [d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))]
        return sorted(folders, reverse=True)
    except Exception:
        return []

def load_results(run_folder, translate_headers, x1, y1, x2, y2, x3, y3, x4, y4):
    results_dir = "results"
    
    if run_folder is None or run_folder == "Latest":
        try:
            run_folders = [os.path.join(results_dir, d) for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))]
            if not run_folders:
                return (None, None, None, go.Figure(), go.Figure(), go.Figure(), go.Figure(), None, None, pd.DataFrame(columns=["Property", "Value"]))
            target_folder = max(run_folders, key=os.path.getmtime)
        except Exception:
            return (None, None, None, go.Figure(), go.Figure(), go.Figure(), go.Figure(), None, None, pd.DataFrame(columns=["Property", "Value"]))
    else:
        target_folder = os.path.join(results_dir, run_folder)
    
    summary_csv = os.path.join(target_folder, "summary.csv")
    results_csv = os.path.join(target_folder, "results.csv")
    env_json = os.path.join(target_folder, "environment.json")
    
    try:
        summary_df = pd.read_csv(summary_csv)
    except Exception:
        summary_df = pd.DataFrame()
        
    try:
        results_df = pd.read_csv(results_csv)
    except Exception:
        results_df = pd.DataFrame()
        
    try:
        with open(env_json, "r") as f:
            env_data = json.load(f)
            env_df = pd.DataFrame(list(env_data.items()), columns=["Property", "Value"])
            env_df["Property"] = env_df["Property"].str.replace("_", " ").str.title()
    except Exception:
        env_df = pd.DataFrame(columns=["Property", "Value"])

    fig_enc, fig_dec, fig_lat, fig_thr = update_all_plots(summary_df, x1, y1, x2, y2, x3, y3, x4, y4)
    
    return (
        summary_df, format_df_headers(summary_df, translate_headers), summary_csv if os.path.exists(summary_csv) else None, 
        fig_enc, fig_dec, fig_lat, fig_thr, 
        format_df_headers(results_df, translate_headers), results_csv if os.path.exists(results_csv) else None, env_df
    )

with gr.Blocks(title="E2EE Thesis Benchmark", fill_height=True) as app:
    gr.Markdown("# E2EE Performance Benchmark")
    gr.Markdown("GUI for thesis research: *Analisis Pengaruh Ukuran Pesan terhadap Kinerja End-to-End Encryption Menggunakan ECDH dan AES-GCM pada Komunikasi Pesan.*")
    
    with gr.Tabs():
        
        with gr.Tab(_("tab_experiment")):
            with gr.Row():
                with gr.Column():
                    gr.Markdown(_("controlled_params"))
                    gr.Markdown("- **ECDH Curve:** SECP256R1\n- **AES Key Size:** 256-bit\n- **Nonce Size:** 12 bytes\n- **Tag Size:** 128-bit\n- **Message Sizes:** 16 B, 64 B, 256 B, 1 KB, 4 KB, 16 KB, 64 KB, 256 KB, 1 MB")
                with gr.Column():
                    reps_slider = gr.Slider(minimum=1, maximum=100, value=30, step=1, label=_("reps_slider"))
                run_btn = gr.Button(_("run_btn"), variant="primary")
            
            log_box = gr.Textbox(label=_("terminal_output"), lines=20, max_lines=20, interactive=False, autoscroll=True)
            
        with gr.Tab(_("tab_aggregate")):
            summary_table = gr.Dataframe(label=_("summary_stats"))
            summary_file = gr.File(label=_("download_summary"))
            ai_summarize_btn = gr.Button(_("summarize_btn"), variant="primary")
            ai_summary_box = gr.Markdown("### Analysis\n*Results will appear here.*")
            
        with gr.Tab(_("tab_visualizations")):
            summary_state = gr.State(pd.DataFrame())
            x_options = [("Message Size (Bytes)", "message_size_bytes")]
            y_options = [
                ("Encryption Time (ms)", "encryption_time_ms"),
                ("Decryption Time (ms)", "decryption_time_ms"),
                ("Latency (ms)", "latency_ms"),
                ("Throughput (KB/s)", "throughput_KB_s"),
                ("Encryption Time (ns)", "encryption_time_ns"),
                ("Decryption Time (ns)", "decryption_time_ns"),
                ("Latency (ns)", "latency_ns"),
                ("Throughput (Bytes/s)", "throughput_bytes_per_s")
            ]
            
            with gr.Accordion(_("advanced_chart"), open=False):
                with gr.Row():
                    preset_dropdown = gr.Dropdown(choices=["Default (ms)", "Default (ns)", "Custom"], value="Default (ms)", label=_("chart_presets"), container=True)
                with gr.Row():
                    with gr.Column():
                        gr.Markdown(f"**{_('chart1')}**")
                        with gr.Row():
                            x1 = gr.Dropdown(choices=x_options, value="message_size_bytes", label=_("x_axis"), container=False)
                            y1 = gr.Dropdown(choices=y_options, value="encryption_time_ms", label=_("y_axis"), container=False)
                    with gr.Column():
                        gr.Markdown(f"**{_('chart2')}**")
                        with gr.Row():
                            x2 = gr.Dropdown(choices=x_options, value="message_size_bytes", label=_("x_axis"), container=False)
                            y2 = gr.Dropdown(choices=y_options, value="decryption_time_ms", label=_("y_axis"), container=False)
                with gr.Row():
                    with gr.Column():
                        gr.Markdown(f"**{_('chart3')}**")
                        with gr.Row():
                            x3 = gr.Dropdown(choices=x_options, value="message_size_bytes", label=_("x_axis"), container=False)
                            y3 = gr.Dropdown(choices=y_options, value="latency_ms", label=_("y_axis"), container=False)
                    with gr.Column():
                        gr.Markdown(f"**{_('chart4')}**")
                        with gr.Row():
                            x4 = gr.Dropdown(choices=x_options, value="message_size_bytes", label=_("x_axis"), container=False)
                            y4 = gr.Dropdown(choices=y_options, value="throughput_KB_s", label=_("y_axis"), container=False)

            with gr.Row():
                img_enc = gr.Plot(label=_("chart1"))
                img_dec = gr.Plot(label=_("chart2"))
            with gr.Row():
                img_lat = gr.Plot(label=_("chart3"))
                img_thr = gr.Plot(label=_("chart4"))
                
        with gr.Tab(_("tab_raw_data")):
            results_table = gr.Dataframe(label=_("raw_obs"))
            results_file = gr.File(label=_("download_results"))
            
        with gr.Tab(_("tab_environment")):
            env_display = gr.Dataframe(label=_("sys_env"), interactive=False, wrap=True)

        with gr.Tab(_("tab_about")):
            gr.Markdown("""# About This Research

This application is the experimental instrument for the thesis: 
**"Analisis Pengaruh Ukuran Pesan terhadap Kinerja End-to-End Encryption Menggunakan ECDH dan AES-GCM pada Komunikasi Pesan"**
*(Analysis of the Effect of Message Size on End-to-End Encryption Performance Using ECDH and AES-GCM in Text Communication)*

## Research Objective
End-to-End Encryption (E2EE) secures communication by encrypting data on the sender's device and only decrypting it on the recipient's device. This research investigates the computational overhead introduced by this process, specifically focusing on how **message size** affects the performance of an E2EE system built with **ECDH** (Elliptic Curve Diffie-Hellman) for key exchange and **AES-GCM** (Advanced Encryption Standard - Galois/Counter Mode) for message encryption.

## Methodology
The experiment isolates message size as the primary independent variable. Nine predetermined message sizes are tested:
`16 B`, `64 B`, `256 B`, `1 KB`, `4 KB`, `16 KB`, `64 KB`, `256 KB`, and `1 MB`.

For each size, the system executes 35 total runs (5 warm-up runs and 30 measured runs) to capture the following primary performance metrics:
1. **Encryption Time:** Time taken to generate a nonce, encrypt the plaintext using AES-256-GCM, and package the ciphertext.
2. **Decryption Time:** Time taken to parse the incoming package, authenticate, and decrypt the ciphertext back to plaintext.
3. **Latency:** Round-trip application latency measured from immediately before encryption until an acknowledgment is received.
4. **Throughput:** Effective end-to-end data transfer rate, calculated as `plaintext size / latency`.

## System Architecture
- **Key Exchange:** SECP256R1 (NIST P-256) curve, performed once per session.
- **Key Derivation Function:** HKDF-SHA256 deriving a 256-bit session key.
- **Message Encryption:** AES-256-GCM with a 12-byte random nonce and a 128-bit authentication tag.
- **Network Transport:** Direct Client-to-Client TCP connection on a controlled Local Area Network (LAN).""")
                
        with gr.Tab(_("tab_settings")):
            gr.Markdown(_("app_prefs"))
            
            with gr.Row():
                with gr.Column(scale=2):
                    gr.Markdown(_("data_mgmt"))
                    run_selector = gr.Dropdown(choices=["Latest"] + get_run_folders(), value="Latest", label=_("data_source"), container=True)
                    refresh_runs_btn = gr.Button(_("refresh_runs"), variant="primary")
                with gr.Column(scale=2):
                    gr.Markdown(_("ui_cust"))
                    translate_headers_cb = gr.Checkbox(label=_("translate_headers"), value=True)
                with gr.Column(scale=2):
                    gr.Markdown("#### " + _("language_sel"))
                    lang_selector = gr.Dropdown(choices=["en", "id"], value=CURRENT_LANG, label=_("language_sel"))
                    
                    def change_lang(lang):
                        set_saved_language(lang)
                        return gr.update()
                        
                    lang_selector.change(fn=change_lang, inputs=[lang_selector], outputs=[])
                with gr.Column(scale=2):
                    gr.Markdown(_("sys"))
                    restart_btn = gr.Button(_("restart_btn"), variant="stop")

    # Wire the event
    run_btn.click(
        fn=lambda: gr.update(interactive=False),
        inputs=None,
        outputs=run_btn,
        queue=False
    ).then(
        fn=run_experiment,
        inputs=[reps_slider, translate_headers_cb, x1, y1, x2, y2, x3, y3, x4, y4],
        outputs=[
            log_box, run_btn, 
            summary_state, summary_table, summary_file, 
            img_enc, img_dec, img_lat, img_thr, 
            results_table, results_file, env_display
        ]
    )
    
    x1.change(fn=plot_plotly, inputs=[summary_state, x1, y1], outputs=img_enc)
    y1.change(fn=plot_plotly, inputs=[summary_state, x1, y1], outputs=img_enc)
    
    x2.change(fn=plot_plotly, inputs=[summary_state, x2, y2], outputs=img_dec)
    y2.change(fn=plot_plotly, inputs=[summary_state, x2, y2], outputs=img_dec)
    
    x3.change(fn=plot_plotly, inputs=[summary_state, x3, y3], outputs=img_lat)
    y3.change(fn=plot_plotly, inputs=[summary_state, x3, y3], outputs=img_lat)
    
    x4.change(fn=plot_plotly, inputs=[summary_state, x4, y4], outputs=img_thr)
    y4.change(fn=plot_plotly, inputs=[summary_state, x4, y4], outputs=img_thr)
    

    def apply_preset(preset, x1_val, y1_val, x2_val, y2_val, x3_val, y3_val, x4_val, y4_val):
        if preset == "Default (ms)":
            return "message_size_bytes", "encryption_time_ms", "message_size_bytes", "decryption_time_ms", "message_size_bytes", "latency_ms", "message_size_bytes", "throughput_KB_s"
        elif preset == "Default (ns)":
            return "message_size_bytes", "encryption_time_ns", "message_size_bytes", "decryption_time_ns", "message_size_bytes", "latency_ns", "message_size_bytes", "throughput_bytes_per_s"
        return x1_val, y1_val, x2_val, y2_val, x3_val, y3_val, x4_val, y4_val

    preset_dropdown.change(
        fn=apply_preset,
        inputs=[preset_dropdown, x1, y1, x2, y2, x3, y3, x4, y4],
        outputs=[x1, y1, x2, y2, x3, y3, x4, y4]
    )

    # Set preset to custom when user manually changes a dropdown
    def set_custom_preset():
        return "Custom"
        
    x1.change(fn=set_custom_preset, inputs=[], outputs=preset_dropdown)
    y1.change(fn=set_custom_preset, inputs=[], outputs=preset_dropdown)
    x2.change(fn=set_custom_preset, inputs=[], outputs=preset_dropdown)
    y2.change(fn=set_custom_preset, inputs=[], outputs=preset_dropdown)
    x3.change(fn=set_custom_preset, inputs=[], outputs=preset_dropdown)
    y3.change(fn=set_custom_preset, inputs=[], outputs=preset_dropdown)
    x4.change(fn=set_custom_preset, inputs=[], outputs=preset_dropdown)
    y4.change(fn=set_custom_preset, inputs=[], outputs=preset_dropdown)

    def update_run_selector():
        choices = ["Latest"] + get_run_folders()
        return gr.update(choices=choices)

    refresh_runs_btn.click(
        fn=update_run_selector,
        inputs=None,
        outputs=run_selector
    )
    
    run_selector.change(
        fn=load_results,
        inputs=[run_selector, translate_headers_cb, x1, y1, x2, y2, x3, y3, x4, y4],
        outputs=[
            summary_state, summary_table, summary_file, 
            img_enc, img_dec, img_lat, img_thr, 
            results_table, results_file, env_display
        ]
    )


    translate_headers_cb.change(
        fn=load_results,
        inputs=[run_selector, translate_headers_cb, x1, y1, x2, y2, x3, y3, x4, y4],
        outputs=[
            summary_state, summary_table, summary_file, 
            img_enc, img_dec, img_lat, img_thr, 
            results_table, results_file, env_display
        ]
    )
    # Auto-load latest results on app launch
    app.load(
        fn=load_results,
        inputs=[run_selector, translate_headers_cb, x1, y1, x2, y2, x3, y3, x4, y4],
        outputs=[
            summary_state, summary_table, summary_file, 
            img_enc, img_dec, img_lat, img_thr, 
            results_table, results_file, env_display
        ]
    )


    def do_restart():
        import os
        import sys
        print("Restarting server...")
        os.execv(sys.executable, [sys.executable] + sys.argv)
        
    restart_btn.click(fn=do_restart)


    def generate_ai_summary(df):
        if df is None or df.empty:
            return "No data to summarize."
            
        import requests
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return "Error: GOOGLE_API_KEY environment variable is not set."

        headers = {
            'Content-Type': 'application/json',
            'X-goog-api-key': api_key
        }
        
        data_str = df.to_string(index=False)
        
        prompt = (
            "You are an academic research assistant. Please analyze the following End-to-End Encryption benchmark summary statistics. "
            "This data is for a thesis titled: 'Analisis Pengaruh Ukuran Pesan terhadap Kinerja End-to-End Encryption Menggunakan ECDH dan AES-GCM pada Komunikasi Pesan'. "
            "Please provide an analytical summary of how the message size affects the performance metrics (Encryption Time, Decryption Time, Latency, and Throughput) based on the data. "
            "CRITICAL INSTRUCTION: Output ONLY a Markdown table summarizing the findings in Indonesian. Do NOT add any introductory or concluding text. Do NOT output paragraphs. Output ONLY the table."
            f"Here is the data:\n\n{data_str}"
        )
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ]
        }
        
        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                return result['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                if attempt == max_retries - 1:
                    return f"Error generating summary after {max_retries} attempts: {str(e)}"
                time.sleep(2)

    ai_summarize_btn.click(
        fn=generate_ai_summary,
        inputs=[summary_table],
        outputs=[ai_summary_box]
    )

if __name__ == "__main__":
    import socket
    env_port = os.environ.get("GRADIO_SERVER_PORT")
    if env_port:
        port = int(env_port)
    else:
        port = 7860
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                print(f"Notice: Port {port} is already in use (e.g., by the Electron app). Falling back to an available port...")
                port = None
    app.queue().launch(server_port=port)

import json
import os

LOCALE_FILE = os.path.join(os.path.dirname(__file__), "..", ".locale")

# Default to English
def get_saved_language():
    if os.path.exists(LOCALE_FILE):
        with open(LOCALE_FILE, "r") as f:
            return f.read().strip()
    return "en"

def set_saved_language(lang):
    with open(LOCALE_FILE, "w") as f:
        f.write(lang)

CURRENT_LANG = get_saved_language()

TRANSLATIONS = {
    "en": {
        "tab_experiment": "Experiment Setup & Execution",
        "tab_aggregate": "Aggregate Statistics",
        "tab_visualizations": "Visualizations",
        "tab_raw_data": "Raw Data Log",
        "tab_environment": "Environment",
        "tab_about": "About Paper",
        "tab_settings": "Settings",
        
        "controlled_params": "### Controlled Parameters (Fixed)",
        "reps_slider": "Measured Repetitions per Size",
        "run_btn": "Run Experiment",
        "terminal_output": "Terminal Output",
        "search_terminal": "Search Terminal Output",
        "search_terminal_placeholder": "Filter log lines (e.g., 1024, Handshake, ERROR, Run 30/30)...",
        "case_sensitive": "Case Sensitive",
        "show_warmup_logs": "Show Warm-up Logs",
        "clear_search": "Clear",
        
        "summary_stats": "Summary Statistics",
        "download_summary": "Download summary.csv",
        "summarize_btn": "Summarize",
        
        "chart_presets": "Chart Presets",
        "chart1": "Chart 1",
        "chart2": "Chart 2",
        "chart3": "Chart 3",
        "chart4": "Chart 4",
        "advanced_chart": "Advanced Chart Configuration (Axes Customization)",
        "x_axis": "X-Axis",
        "y_axis": "Y-Axis",
        
        "raw_obs": "Raw Observations (results.csv)",
        "download_results": "Download results.csv",
        
        "sys_env": "System Environment Configuration",
        
        "app_prefs": "### Application Preferences",
        "data_mgmt": "#### Data Management",
        "data_source": "Data Source (Saved Run)",
        "refresh_runs": "Refresh Run List",
        "ui_cust": "#### UI Customization",
        "translate_headers": "Translate Data Headers (Snake Case -> Title Case)",
        "sys": "#### System",
        "restart_btn": "Restart Server",
        "language_sel": "Language / Bahasa",
        
        "starting_exp": "Starting experiment: {sizes} payload sizes, {runs} measured runs per size (+ {warmups} warm-ups)",
        "exec_order": "Execution sequence: {plan}",

        "msg_size": "================================================================================\n  MESSAGE SIZE: {size_label}  —  [Size {idx}/{total_sizes}]\n================================================================================",
        "warmup_phase_start": "  [WARM-UP PHASE] Executing {warmups} warm-up trials (discarded from CSV)...",
        "warmup_trial_log": "  • Warm-up {w:>2}/{warmups:<2}                │ {status:<4} │ Enc: {enc_ms:>7.3f} ms │ Dec: {dec_ms:>7.3f} ms │ RTT: {lat_ms:>7.3f} ms  (discarded)",
        "measured_phase_start": "  [MEASURED PHASE] Executing {runs} measured trials (recorded to CSV)...",
        "measured_trial_log": "  • Trial   {m:>2}/{runs:<2} (Run {current:>3}/{total:<3}) │ {status:<4} │ Enc: {enc_ms:>7.3f} ms │ Dec: {dec_ms:>7.3f} ms │ RTT: {lat_ms:>7.3f} ms │ Thr: {thr_str:>11}",
        "exp_complete": "Benchmark completed successfully!",
        "total_time": "Total time: {duration}",
        "results_saved": "Results saved to: {filename}",
        
        "err_run": "Error during run: {e}",
        
        "starting_receiver": "Starting receiver on {host}:{port}...",
        "receiver_sender_connected": "Sender connected.",
        
        "sender_connecting": "Connecting to receiver on {host}:{port}...",
        "sender_connected": "Connected."
    },
    "id": {
        "tab_experiment": "Pengaturan & Eksekusi Eksperimen",
        "tab_aggregate": "Statistik Agregat",
        "tab_visualizations": "Visualisasi",
        "tab_raw_data": "Log Data Mentah",
        "tab_environment": "Lingkungan",
        "tab_about": "Tentang Makalah",
        "tab_settings": "Pengaturan",
        
        "controlled_params": "### Parameter Terkontrol (Tetap)",
        "reps_slider": "Pengulangan yang Diukur per Ukuran",
        "run_btn": "Jalankan Eksperimen",
        "terminal_output": "Keluaran Terminal",
        "search_terminal": "Cari Keluaran Terminal",
        "search_terminal_placeholder": "Saring baris log (mis., 1024, Handshake, ERROR, Run 30/30)...",
        "case_sensitive": "Peka Huruf Besar/Kecil",
        "show_warmup_logs": "Tampilkan Log Warm-up",
        "clear_search": "Bersihkan",
        
        "summary_stats": "Statistik Ringkasan",
        "download_summary": "Unduh summary.csv",
        "summarize_btn": "Ringkas",
        
        "chart_presets": "Prasetel Grafik",
        "chart1": "Grafik 1",
        "chart2": "Grafik 2",
        "chart3": "Grafik 3",
        "chart4": "Grafik 4",
        "advanced_chart": "Konfigurasi Grafik Lanjutan (Kustomisasi Sumbu)",
        "x_axis": "Sumbu-X",
        "y_axis": "Sumbu-Y",
        
        "raw_obs": "Observasi Mentah (results.csv)",
        "download_results": "Unduh results.csv",
        
        "sys_env": "Konfigurasi Lingkungan Sistem",
        
        "app_prefs": "### Preferensi Aplikasi",
        "data_mgmt": "#### Manajemen Data",
        "data_source": "Sumber Data (Proses Tersimpan)",
        "refresh_runs": "Segarkan Daftar Proses",
        "ui_cust": "#### Kustomisasi Antarmuka",
        "translate_headers": "Terjemahkan Tajuk Data (Snake Case -> Title Case)",
        "sys": "#### Sistem",
        "restart_btn": "Mulai Ulang Server",
        "language_sel": "Language / Bahasa",
        
        "starting_exp": "Memulai eksperimen: {sizes} ukuran muatan, {runs} proses terukur per ukuran (+ {warmups} pemanasan)",
        "exec_order": "Urutan eksekusi: {plan}",

        "msg_size": "================================================================================\n  UKURAN PESAN: {size_label}  —  [Ukuran {idx}/{total_sizes}]\n================================================================================",
        "warmup_phase_start": "  [FASE WARM-UP] Menjalankan {warmups} percobaan pemanasan (tidak disimpan ke CSV)...",
        "warmup_trial_log": "  • Pemanasan {w:>2}/{warmups:<2}              │ {status:<4} │ Enk: {enc_ms:>7.3f} ms │ Dek: {dec_ms:>7.3f} ms │ RTT: {lat_ms:>7.3f} ms  (diabaikan)",
        "measured_phase_start": "  [FASE TERUKUR] Menjalankan {runs} percobaan terukur (disimpan ke CSV)...",
        "measured_trial_log": "  • Uji Coba {m:>2}/{runs:<2} (Proses {current:>3}/{total:<3}) │ {status:<4} │ Enk: {enc_ms:>7.3f} ms │ Dek: {dec_ms:>7.3f} ms │ RTT: {lat_ms:>7.3f} ms │ Thr: {thr_str:>11}",
        "exp_complete": "Benchmark berhasil diselesaikan!",
        "total_time": "Total waktu: {duration}",
        "results_saved": "Hasil disimpan di: {filename}",
        
        "err_run": "Kesalahan saat memproses: {e}",
        
        "starting_receiver": "Memulai penerima di {host}:{port}...",
        "receiver_sender_connected": "Pengirim terhubung.",
        
        "sender_connecting": "Menghubungkan ke penerima di {host}:{port}...",
        "sender_connected": "Terhubung."
    }
}

def _(key, **kwargs):
    lang = CURRENT_LANG
    if lang not in TRANSLATIONS:
        lang = "en"
    
    text = TRANSLATIONS[lang].get(key, TRANSLATIONS["en"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text

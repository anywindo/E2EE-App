import gradio as gr
import sqlite3
import datetime
import os
import re
import pandas as pd
import time
import plotly.express as px

from src import crypto
from src import protocol
from src.logger import get_logger

logger = get_logger("chat")
DB_FILE = "chat.db"


def append_log(log_str, new_msg):
    """Helper to append log messages and compress consecutive duplicates."""
    new_msg = new_msg.strip()
    if not new_msg:
        return log_str
        
    lines = log_str.strip().split('\n')
    if not lines or not lines[0]:
        return new_msg + "\n"
        
    last_line = lines[-1]
    
    # Check if the last line is the same message (possibly with [xN times])
    match = re.match(r"^(.*?) \[x(\d+) times\]$", last_line)
    if match:
        base_msg = match.group(1)
        count = int(match.group(2))
    else:
        base_msg = last_line
        count = 1
        
    if base_msg == new_msg:
        # Increment the count and replace the last line
        lines[-1] = f"{base_msg} [x{count + 1} times]"
        return "\n".join(lines) + "\n"
    else:
        # New message, just append
        if not log_str.endswith('\n') and log_str != "":
            return log_str + "\n" + new_msg + "\n"
        return log_str + new_msg + "\n"


def filter_terminal_output(raw_log, query="", case_sensitive=False, show_warmup=False):
    """Filters terminal/crypto log lines by warm-up visibility and search query while preserving line numbers."""
    if not raw_log:
        return ""

    raw_lines = raw_log.splitlines()
    visible_lines = []
    in_warmup_block = False

    for line in raw_lines:
        if "[WARM-UP PHASE]" in line or "[FASE WARM-UP]" in line:
            in_warmup_block = True
        elif "[MEASURED PHASE]" in line or "[FASE TERUKUR]" in line or "MESSAGE SIZE:" in line or "UKURAN PESAN:" in line or "========== " in line:
            in_warmup_block = False

        if not show_warmup and (in_warmup_block or "Warm-up" in line or "Pemanasan" in line or "[WARM-UP" in line):
            continue
        visible_lines.append(line)

    if not query or not query.strip():
        return "\n".join(visible_lines)

    needle = query if case_sensitive else query.lower()
    matched = []
    for idx, line in enumerate(visible_lines, start=1):
        haystack = line if case_sensitive else line.lower()
        if needle in haystack:
            matched.append(f"[L{idx}] {line}")

    header = f"--- Showing {len(matched)} of {len(visible_lines)} lines matching '{query}' ---\n"
    if not matched:
        return header + "(No matching lines)"
    return header + "\n".join(matched)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist and clear stale data on startup."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS public_keys
                 (user TEXT PRIMARY KEY, public_key BLOB)""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  sender TEXT,
                  nonce BLOB,
                  ciphertext BLOB,
                  tag BLOB,
                  timestamp TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS performance_metrics
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message_id INTEGER,
                  message_size_bytes INTEGER,
                  action TEXT,
                  latency_ms REAL,
                  throughput_kbs REAL,
                  processing_time_ms REAL,
                  timestamp TEXT)""")
    # Fresh session every time the server starts
    c.execute("DELETE FROM public_keys")
    c.execute("DELETE FROM messages")
    c.execute("DELETE FROM performance_metrics")
    conn.commit()
    conn.close()
    logger.info("Database initialised (tables cleared for new session).")


def _db():
    return sqlite3.connect(DB_FILE)


# ---------------------------------------------------------------------------
# Global State
# ---------------------------------------------------------------------------

ACTIVE_USERS = set()

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login(identity, session, chatbot):
    """Generate a keypair, store the public key, and try to derive the shared
    secret if the peer has already registered."""

    if not identity:
        return (
            gr.update(),        # client_view
            chatbot,            # chatbot history
            "",                 # crypto_log
            "Please select an identity.",  # status
            session,            # session state (unchanged)
            gr.update(visible=True),  # identity_dd
            gr.update(visible=True),  # login_btn
            gr.update(visible=False), # logout_btn
        )


    # ---- Alice or Bob ----
    ACTIVE_USERS.add(identity)

    priv_key, pub_key = crypto.generate_keypair()
    pub_bytes = protocol.serialize_public_key(pub_key)

    conn = _db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO public_keys (user, public_key) VALUES (?, ?)",
        (identity, pub_bytes),
    )
    conn.commit()

    log = f"[{identity}] Generated ephemeral ECDH keypair.\n"
    log += f"[{identity}] Public key saved to database ({len(pub_bytes)} bytes).\n"

    # Check if the peer already registered
    peer = "Bob" if identity == "Alice" else "Alice"
    c.execute("SELECT public_key FROM public_keys WHERE user = ?", (peer,))
    row = c.fetchone()
    conn.close()

    peer_pub_bytes = None
    shared_key = None
    if row:
        peer_pub_bytes = row[0]
        peer_pub_key = protocol.deserialize_public_key(peer_pub_bytes)
        shared_key = crypto.derive_shared_key(priv_key, peer_pub_key)
        log += f"[{identity}] Found {peer}'s public key → derived shared AES-GCM session key\n"
        logger.info("%s derived shared key with %s", identity, peer)
    else:
        log += f"[{identity}] Waiting for {peer} to join…\n"

    previous_identity = session.get("previous_identity")
    if identity == previous_identity:
        last_msg_id = session.get("last_msg_id", 0)
        chatbot.append({"role": "assistant", "content": "🔒 Your security code changed."})
    else:
        last_msg_id = 0
        chatbot = []

    # Store everything that belongs to THIS browser tab in gr.State
    session = {
        "identity": identity,
        "priv_key": priv_key,
        "shared_key": shared_key,
        "peer_pub_bytes": peer_pub_bytes,
        "last_msg_id": last_msg_id,
        "previous_identity": identity,
    }

    return (
        gr.update(visible=True),   # client_view
        chatbot,                   # chatbot history
        log,                       # crypto_log
        f"Logged in as **{identity}**",
        session,
        gr.update(visible=False),  # identity_dd
        gr.update(visible=False),  # login_btn
        gr.update(visible=True),   # logout_btn
    )


# ---------------------------------------------------------------------------
# Derive shared key lazily (if peer joined after us)
# ---------------------------------------------------------------------------

def _sync_peer_key(session, log, history=None):
    """If we don't have the shared key yet, or the peer changed their key, sync it."""
    if not session or "identity" not in session:
        return session, log

    identity = session["identity"]
    peer = "Bob" if identity == "Alice" else "Alice"

    conn = _db()
    c = conn.cursor()
    c.execute("SELECT public_key FROM public_keys WHERE user = ?", (peer,))
    row = c.fetchone()
    conn.close()

    if row:
        peer_pub_bytes = row[0]
        # Only derive a new shared key if we don't have one, or if the peer's public key changed
        if session.get("shared_key") is None or session.get("peer_pub_bytes") != peer_pub_bytes:
            peer_pub_key = protocol.deserialize_public_key(peer_pub_bytes)
            shared_key = crypto.derive_shared_key(session["priv_key"], peer_pub_key)
            
            # If we ALREADY had a peer_pub_bytes and it changed, log it and append security message
            if session.get("peer_pub_bytes") is not None and session.get("peer_pub_bytes") != peer_pub_bytes:
                log += f"[{identity}] Detected {peer} changed their key. Derived new AES-GCM session key.\n"
                if history is not None:
                    history.append({"role": "assistant", "content": "🔒 Your security code changed."})
            else:
                log += f"[{identity}] Found {peer}'s public key → derived shared AES-GCM session key\n"
                logger.info("%s derived shared key with %s", identity, peer)
            
            session["shared_key"] = shared_key
            session["peer_pub_bytes"] = peer_pub_bytes

    return session, log


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_message(message, history, log, session):
    if not message or not message.strip():
        return "", history, log, session

    if not session or "identity" not in session:
        log += "Not logged in.\n"
        return message, history, log, session

    identity = session["identity"]
    session, log = _sync_peer_key(session, log, history)

    if session.get("shared_key") is None:
        peer = "Bob" if identity == "Alice" else "Alice"
        log = append_log(log, f"[{identity}] Cannot encrypt — {peer} has not joined yet.")
        return message, history, log, session

    shared_key = session["shared_key"]

    # Encrypt
    plaintext = message.encode("utf-8")
    
    start_t = time.perf_counter()
    nonce, ciphertext, tag = crypto.encrypt(shared_key, plaintext)
    end_t = time.perf_counter()
    
    enc_time_ms = (end_t - start_t) * 1000
    throughput_kbs = (len(plaintext) / 1024) / (end_t - start_t) if (end_t - start_t) > 0 else 0

    log += "\n═══ SENDING MESSAGE ═══\n"
    log += f"  Plaintext      : {message}\n"
    log += f"  Nonce  (12 B)  : {nonce.hex()}\n"
    log += f"  Ciphertext ({len(ciphertext):>3} B): {ciphertext.hex()}\n"
    log += f"  Auth Tag (16 B): {tag.hex()}\n"
    log += "-----------------------\n"
    log += "\n═══ PERFORMANCE METRICS ═══\n"
    log += f"  --> Encrypt Time : {enc_time_ms:.3f} ms\n"
    log += f"  --> Throughput   : {throughput_kbs:.1f} KB/s\n"
    log += "-----------------------\n"

    logger.info(f"[{identity}] Sending encrypted message to untrusted server.")
    logger.debug(f"Nonce (12B): {nonce.hex()} | Ciphertext ({len(ciphertext)}B) | Tag (16B): {tag.hex()}")
    
    # Write to DB (the "untrusted server")
    conn = _db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (sender, nonce, ciphertext, tag, timestamp) VALUES (?,?,?,?,?)",
        (identity, nonce, ciphertext, tag, datetime.datetime.now().isoformat()),
    )
    msg_id = c.lastrowid
    
    # Store encryption metric
    c.execute(
        "INSERT INTO performance_metrics (message_id, message_size_bytes, action, processing_time_ms, throughput_kbs, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (msg_id, len(plaintext), "encrypt", enc_time_ms, throughput_kbs, datetime.datetime.now().isoformat())
    )
    
    conn.commit()
    conn.close()
    log += "  → Written to SQLite (untrusted server).\n"
    log += "-----------------------\n"

    history.append({"role": "user", "content": message})
    return "", history, log, session


# ---------------------------------------------------------------------------
# Receive
# ---------------------------------------------------------------------------

def receive_messages(history, log, session):
    if not session or "identity" not in session:
        return history, log, session

    identity = session["identity"]
    session, log = _sync_peer_key(session, log, history)

    if session.get("shared_key") is None:
        peer = "Bob" if identity == "Alice" else "Alice"
        log = append_log(log, f"[{identity}] Cannot decrypt — {peer} has not joined yet.")
        return history, log, session

    shared_key = session["shared_key"]
    last_id = session["last_msg_id"]
    peer = "Bob" if identity == "Alice" else "Alice"

    conn = _db()
    c = conn.cursor()
    c.execute(
        "SELECT id, nonce, ciphertext, tag, timestamp FROM messages "
        "WHERE sender = ? AND id > ? ORDER BY id ASC",
        (peer, last_id),
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        log = append_log(log, f"\n[{identity}] No new messages from {peer}.\n")
        return history, log, session

    for msg_id, nonce, ciphertext, tag, ts_str in rows:
        log += "\n═══ RECEIVING MESSAGE ═══\n"
        log += f"  DB Row ID      : {msg_id}\n"
        log += f"  Nonce  (12 B)  : {nonce.hex()}\n"
        log += f"  Ciphertext ({len(ciphertext):>3} B): {ciphertext.hex()}\n"
        log += f"  Auth Tag (16 B): {tag.hex()}\n"
        log += "-----------------------\n"

        try:
            start_t = time.perf_counter()
            plaintext_bytes = crypto.decrypt(shared_key, nonce, ciphertext, tag)
            end_t = time.perf_counter()
            
            plaintext = plaintext_bytes.decode("utf-8")
            
            dec_time_ms = (end_t - start_t) * 1000
            throughput_kbs = (len(plaintext_bytes) / 1024) / (end_t - start_t) if (end_t - start_t) > 0 else 0
            
            e2e_latency_ms = 0.0
            if ts_str:
                sent_time = datetime.datetime.fromisoformat(ts_str)
                e2e_latency_ms = (datetime.datetime.now() - sent_time).total_seconds() * 1000

            # Store decryption metric
            conn2 = _db()
            c2 = conn2.cursor()
            c2.execute(
                "INSERT INTO performance_metrics (message_id, message_size_bytes, action, latency_ms, processing_time_ms, throughput_kbs, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, len(plaintext_bytes), "decrypt", e2e_latency_ms, dec_time_ms, throughput_kbs, datetime.datetime.now().isoformat())
            )
            conn2.commit()
            conn2.close()

            logger.info(f"[{identity}] Successfully decrypted message (ID: {msg_id}) from {peer}.")
            logger.debug(f"Decrypted plaintext: '{plaintext}'")
            log += f"  Decrypt + Auth : SUCCESS\n"
            log += f"  Plaintext      : {plaintext}\n"
            log += "═══ PERFORMANCE METRICS ═══\n"
            log += f"  --> Decrypt Time : {dec_time_ms:.3f} ms\n"
            log += f"  --> Throughput   : {throughput_kbs:.1f} KB/s\n"
            log += f"  --> E2E Latency  : {e2e_latency_ms:.1f} ms\n"
            log += "-----------------------\n"
            history.append({"role": "assistant", "content": plaintext})
        except Exception as e:
            logger.warning(f"[{identity}] Failed to decrypt message (ID: {msg_id}) from {peer}. Reason: {e}")
            log += f"  Decrypt + Auth : FAILED ({e})\n"
            log += "-----------------------\n"
            log += "\n═══ KEY REGENERATION ═══\n"
            log += "  PERFECT FORWARD SECRECY IN ACTION:\n"
            log += "  This message was encrypted with a previous session key.\n"
            log += "  Because you logged out, a new ephemeral keypair was generated.\n"
            log += "  The old session key was destroyed and cannot be recovered!\n"
            log += "  (Please restart the python server to clear the SQLite DB)\n"
            history.append({"role": "assistant", "content": "[DECRYPTION FAILED]"})
            log += "-----------------------\n"

        session["last_msg_id"] = msg_id

    return history, log, session


# ---------------------------------------------------------------------------
# Database Browser (Server View)
# ---------------------------------------------------------------------------

def view_db():
    conn = _db()
    c = conn.cursor()

    c.execute("SELECT user, hex(public_key) FROM public_keys")
    keys = c.fetchall()

    c.execute(
        "SELECT id, sender, hex(nonce), hex(ciphertext), hex(tag), timestamp "
        "FROM messages ORDER BY id DESC LIMIT 50"
    )
    msgs = c.fetchall()

    c.execute(
        "SELECT id, message_id, message_size_bytes, action, latency_ms, throughput_kbs, processing_time_ms, timestamp "
        "FROM performance_metrics ORDER BY id DESC LIMIT 50"
    )
    metrics = c.fetchall()
    
    conn.close()

    # Format data for gr.Dataframe
    keys_df = pd.DataFrame(
        [(u, f"{pk[:40]}...") for u, pk in keys],
        columns=["User", "Public Key (Hex, truncated)"]
    )
    
    msgs_df = pd.DataFrame(
        [(mid, sender, f"{nonce[:16]}...", f"{ct[:20]}...", tag, ts) for mid, sender, nonce, ct, tag, ts in msgs],
        columns=["ID", "Sender", "Nonce", "Ciphertext", "Tag", "Time"]
    )

    metrics_df = pd.DataFrame(
        metrics,
        columns=["ID", "Message ID", "Message Size (Bytes)", "Action", "Latency (ms)", "Throughput (KB/s)", "Processing Time (ms)", "Time"]
    )
    
    metrics_df["Encryption Time (ms)"] = metrics_df.apply(lambda row: row["Processing Time (ms)"] if row["Action"] == "encrypt" else None, axis=1)
    metrics_df["Decryption Time (ms)"] = metrics_df.apply(lambda row: row["Processing Time (ms)"] if row["Action"] == "decrypt" else None, axis=1)

    enc_df = metrics_df.dropna(subset=["Encryption Time (ms)"])
    enc_fig = px.scatter(enc_df, x="Message Size (Bytes)", y="Encryption Time (ms)", title="Encryption Time vs Message Size", trendline="ols" if len(enc_df) > 1 else None)
    
    dec_df = metrics_df.dropna(subset=["Decryption Time (ms)"])
    dec_fig = px.scatter(dec_df, x="Message Size (Bytes)", y="Decryption Time (ms)", title="Decryption Time vs Message Size", trendline="ols" if len(dec_df) > 1 else None)
    
    lat_df = metrics_df.dropna(subset=["Latency (ms)"])
    lat_fig = px.scatter(lat_df, x="Message Size (Bytes)", y="Latency (ms)", title="End-to-End Latency vs Message Size", trendline="ols" if len(lat_df) > 1 else None)
    
    thr_df = metrics_df.dropna(subset=["Throughput (KB/s)"])
    thr_fig = px.scatter(thr_df, x="Message Size (Bytes)", y="Throughput (KB/s)", color="Action", title="Throughput vs Message Size", trendline="ols" if len(thr_df) > 1 else None)

    if not enc_df.empty:
        enc_agg = enc_df.groupby("Message Size (Bytes)")["Encryption Time (ms)"].agg(["median", "std"]).reset_index().fillna(0)
        enc_agg_fig = px.line(enc_agg, x="Message Size (Bytes)", y="median", error_y="std", title="Encryption Time (Median ± Std)", markers=True, log_x=True)
        enc_agg_fig.update_yaxes(title_text="Time (ms)")
    else:
        enc_agg_fig = px.line(title="Encryption Time (Median ± Std)")

    if not dec_df.empty:
        dec_agg = dec_df.groupby("Message Size (Bytes)")["Decryption Time (ms)"].agg(["median", "std"]).reset_index().fillna(0)
        dec_agg_fig = px.line(dec_agg, x="Message Size (Bytes)", y="median", error_y="std", title="Decryption Time (Median ± Std)", markers=True, log_x=True)
        dec_agg_fig.update_yaxes(title_text="Time (ms)")
    else:
        dec_agg_fig = px.line(title="Decryption Time (Median ± Std)")

    if not lat_df.empty:
        lat_agg = lat_df.groupby("Message Size (Bytes)")["Latency (ms)"].agg(["median", "std"]).reset_index().fillna(0)
        lat_agg_fig = px.line(lat_agg, x="Message Size (Bytes)", y="median", error_y="std", title="End-to-End Latency (Median ± Std)", markers=True, log_x=True)
        lat_agg_fig.update_yaxes(title_text="Latency (ms)")
    else:
        lat_agg_fig = px.line(title="End-to-End Latency (Median ± Std)")
        
    if not thr_df.empty:
        thr_agg = thr_df.groupby(["Message Size (Bytes)", "Action"])["Throughput (KB/s)"].agg(["median", "std"]).reset_index().fillna(0)
        thr_agg_fig = px.line(thr_agg, x="Message Size (Bytes)", y="median", error_y="std", color="Action", title="Throughput (Median ± Std)", markers=True, log_x=True)
        thr_agg_fig.update_yaxes(title_text="Throughput (KB/s)")
    else:
        thr_agg_fig = px.line(title="Throughput (Median ± Std)")

    return keys_df, msgs_df, metrics_df, enc_fig, dec_fig, lat_fig, thr_fig, enc_agg_fig, dec_agg_fig, lat_agg_fig, thr_agg_fig


def logout(session, chatbot):
    identity = session.get("identity")
    if identity in ACTIVE_USERS:
        ACTIVE_USERS.remove(identity)
    
    if identity:
        session["previous_identity"] = identity
        
    return (
        gr.update(visible=False),
        chatbot,
        "",
        "Logged out.",
        {},
        gr.update(visible=True),
        gr.update(visible=True),
        gr.update(visible=False),
    )


def regenerate_key(log, session, chatbot):
    if not session or "identity" not in session:
        return log, session, chatbot

    identity = session["identity"]
    priv_key, pub_key = crypto.generate_keypair()
    pub_bytes = protocol.serialize_public_key(pub_key)

    session["priv_key"] = priv_key
    session["pub_bytes"] = pub_bytes
    session["shared_key"] = None

    conn = _db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO public_keys (user, public_key) VALUES (?, ?)",
        (identity, pub_bytes),
    )
    conn.commit()
    conn.close()

    logger.info(f"[{identity}] Regenerated fresh ephemeral ECDH keypair.")
    log += f"\n[{identity}] Regenerated fresh ephemeral ECDH keypair.\n"
    log += f"[{identity}] Saved new public key to server database ({len(pub_bytes)} bytes).\n"

    session, log = _sync_peer_key(session, log, chatbot)
    
    chatbot.append({"role": "assistant", "content": "🔒 Your security code changed."})
    
    return log, session, chatbot


def restart_server(history, log, session):
    init_db()
    ACTIVE_USERS.clear()

    log += "\n══════ SERVER RESTARTED ══════\n"
    log += "  Database tables (public_keys, messages) have been wiped.\n"
    log += "  All active user sessions cleared.\n"

    if session and "identity" in session:
        identity = session["identity"]
        priv_key, pub_key = crypto.generate_keypair()
        pub_bytes = protocol.serialize_public_key(pub_key)
        session["priv_key"] = priv_key
        session["pub_bytes"] = pub_bytes
        session["shared_key"] = None
        session["last_msg_id"] = 0
        ACTIVE_USERS.add(identity)

        conn = _db()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO public_keys (user, public_key) VALUES (?, ?)",
            (identity, pub_bytes),
        )
        conn.commit()
        conn.close()
        log += f"  [{identity}] Re-registered new keypair on fresh database.\n"

    return [], log, session




def update_pt_plots(df, plot_type, trendline, log_x, log_y):
    import plotly.express as px
    if df is None or df.empty:
        return None, None, None, None

    t_mode = None if trendline == "None" else trendline.lower()

    if plot_type == "Line (Aggregated)":
        # Group by and get median/std
        enc_agg = df.groupby("Message Size (Bytes)")["Encryption Time (ms)"].agg(["median", "std"]).reset_index().fillna(0)
        enc_fig = px.line(enc_agg, x="Message Size (Bytes)", y="median", error_y="std", title="Encryption Time", markers=True, log_x=log_x, log_y=log_y)
        
        dec_agg = df.groupby("Message Size (Bytes)")["Decryption Time (ms)"].agg(["median", "std"]).reset_index().fillna(0)
        dec_fig = px.line(dec_agg, x="Message Size (Bytes)", y="median", error_y="std", title="Decryption Time", markers=True, log_x=log_x, log_y=log_y)
        
        lat_agg = df.groupby("Message Size (Bytes)")["Latency (ms)"].agg(["median", "std"]).reset_index().fillna(0)
        lat_fig = px.line(lat_agg, x="Message Size (Bytes)", y="median", error_y="std", title="End-to-End Latency", markers=True, log_x=log_x, log_y=log_y)
        
        thr_agg = df.groupby("Message Size (Bytes)")["Throughput (KB/s)"].agg(["median", "std"]).reset_index().fillna(0)
        thr_fig = px.line(thr_agg, x="Message Size (Bytes)", y="median", error_y="std", title="Throughput", markers=True, log_x=log_x, log_y=log_y)
    else:
        # Scatter
        enc_fig = px.scatter(df, x="Message Size (Bytes)", y="Encryption Time (ms)", title="Encryption Time", trendline=t_mode, log_x=log_x, log_y=log_y)
        dec_fig = px.scatter(df, x="Message Size (Bytes)", y="Decryption Time (ms)", title="Decryption Time", trendline=t_mode, log_x=log_x, log_y=log_y)
        lat_fig = px.scatter(df, x="Message Size (Bytes)", y="Latency (ms)", title="End-to-End Latency", trendline=t_mode, log_x=log_x, log_y=log_y)
        thr_fig = px.scatter(df, x="Message Size (Bytes)", y="Throughput (KB/s)", title="Throughput", trendline=t_mode, log_x=log_x, log_y=log_y)

    enc_fig.update_yaxes(title_text="Time (ms)")
    dec_fig.update_yaxes(title_text="Time (ms)")
    lat_fig.update_yaxes(title_text="Latency (ms)")
    thr_fig.update_yaxes(title_text="Throughput (KB/s)")

    return enc_fig, dec_fig, lat_fig, thr_fig

def run_planned_testing(search_query="", case_sensitive=False, show_warmup=False):
    import subprocess
    import os
    try:
        result = subprocess.run([sys.executable if "sys" in globals() else "python", "run_e2e.py"], capture_output=True, text=True, timeout=120)
        output = result.stdout
        if result.stderr:
            output += "\nSTDERR:\n" + result.stderr
            
        import pandas as pd
        import glob
        import plotly.express as px
        base = os.path.abspath("results")
        
        # Find the newest run folder
        run_folders = [f for f in glob.glob(os.path.join(base, "run_*")) if os.path.isdir(f)]
        
        df = None
        enc_fig, dec_fig, lat_fig, thr_fig = None, None, None, None
        
        if run_folders:
            latest_folder = max(run_folders, key=os.path.getctime)
            latest_file = os.path.join(latest_folder, "results.csv")
            
            if os.path.exists(latest_file):
                df = pd.read_csv(latest_file)
            
            if df is not None and not df.empty:
                df["Encryption Time (ms)"] = df["encryption_time_ns"] / 1_000_000
                df["Decryption Time (ms)"] = df["decryption_time_ns"] / 1_000_000
                df["Latency (ms)"] = df["latency_ns"] / 1_000_000
                df["Throughput (KB/s)"] = df["throughput_bytes_per_s"] / 1_024
                df["Message Size (Bytes)"] = df["message_size_bytes"]

                # Initial plots (Line, log_x=True)
                enc_fig, dec_fig, lat_fig, thr_fig = update_pt_plots(df, "Line (Aggregated)", "None", True, False)

        filtered_output = filter_terminal_output(output, search_query, case_sensitive, show_warmup)
        return output, filtered_output, enc_fig, dec_fig, lat_fig, thr_fig, df, df
    except Exception as e:
        err_msg = f"Error running planned testing: {str(e)}"
        return err_msg, filter_terminal_output(err_msg, search_query, case_sensitive, show_warmup), None, None, None, None, None, None

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

init_db()

SELECTABLE_CSS = """
textarea, pre, code, .prose, table, .table-wrap, [data-testid="textbox"] textarea, .output-markdown {
    user-select: text !important;
    -webkit-user-select: text !important;
    cursor: text !important;
}
"""

with gr.Blocks(title="E2EE Chat Demo", css=SELECTABLE_CSS) as app:
    gr.Markdown("# E2EE Interactive  Chat")
    gr.Markdown(
        ""
        ""
    )

    # Per-tab session state (keys, identity, cursor)
    session = gr.State(value={})

    with gr.Tabs():
        with gr.Tab("Chat Client"):
            with gr.Row(equal_height=True):
                identity_dd = gr.Dropdown(
                    choices=["Alice", "Bob"],
                    label="Select Identity",
                    scale=3
                )
                login_status = gr.Markdown(value="", scale=3)
                login_btn = gr.Button("Login", variant="primary", scale=1)
                logout_btn = gr.Button("Logout", variant="secondary", scale=1, visible=False)

            # ---- Client View (Alice / Bob) ----
            with gr.Column(visible=False) as client_view:
                with gr.Row():
                    with gr.Column(scale=1):
                        chatbot = gr.Chatbot(label="Chat Window", height=550, group_consecutive_messages=False)
                        with gr.Row(equal_height=True):
                            msg_input = gr.Textbox(
                                placeholder="Type a message…",
                                show_label=False,
                                scale=4,
                                container=False
                            )
                            send_btn = gr.Button("Send", variant="primary", scale=1, min_width=80)

                    with gr.Column(scale=1):
                        raw_crypto_log = gr.State("")
                        with gr.Row(equal_height=True):
                            crypto_search_box = gr.Textbox(
                                placeholder="Search Crypto Log (e.g., Nonce, Auth Tag, Decrypt)...",
                                label="Search Crypto Log",
                                scale=4,
                                container=True
                            )
                            crypto_case_sensitive = gr.Checkbox(
                                label="Case Sensitive",
                                value=False,
                                scale=1
                            )
                            crypto_clear_search_btn = gr.Button(
                                "Clear",
                                variant="secondary",
                                scale=1
                            )
                        crypto_log = gr.Textbox(
                            label="Crypto Log (Verbose)",
                            lines=24,
                            max_lines=24,
                            interactive=False,
                            autoscroll=True,
                            elem_id="crypto_log_box",
                        )

                with gr.Accordion("Settings", open=True):
                    with gr.Row():
                        with gr.Column():
                            gr.Markdown("#### Auto Refresh & Message Fetching")
                            with gr.Row():
                                refresh_btn = gr.Button("Check for New Messages", variant="primary")
                                auto_refresh = gr.Checkbox(label="Auto Refresh", value=True)
                            timer = gr.Timer(1, active=True)
                            
                        with gr.Column():
                            gr.Markdown("#### Key Management & Server Maintenance")
                            with gr.Row():
                                regen_key_btn = gr.Button("Regenerate Ephemeral Key", variant="secondary")
                                reset_server_btn = gr.Button("Restart Server / Wipe DB", variant="stop")





        

        # ---- Server View (Database Browser) ----
        with gr.Tab("Database Browser"):
            with gr.Row(equal_height=True):
                with gr.Column(scale=3):
                    gr.Markdown("## Database Browser")
                    gr.Markdown(
                        "SQLite database used for the chat application."
                    )
                with gr.Column(scale=1):
                    refresh_db_btn = gr.Button("Refresh Database View", variant="primary")
                    db_auto_refresh = gr.Checkbox(label="Auto Refresh (1s)", value=True)
                
            db_timer = gr.Timer(1, active=True)
            
            with gr.Accordion("🔑 Public Keys Table", open=True):
                db_keys_df = gr.Dataframe(interactive=False, wrap=True)
                
            with gr.Accordion("✉️ Messages Table", open=True):
                db_msgs_df = gr.Dataframe(interactive=False, wrap=True)

        # ---- Performance Tab ----
        with gr.Tab("Performance"):
            with gr.Row(equal_height=True):
                with gr.Column(scale=3):
                    gr.Markdown("## Performance Metrics")
                    gr.Markdown("View encryption/decryption latency, throughput, and end-to-end latency.")
                with gr.Column(scale=1):
                    refresh_perf_btn = gr.Button("Refresh Metrics", variant="primary")
                    perf_auto_refresh = gr.Checkbox(label="Auto Refresh (1s)", value=True)
                    
            perf_timer = gr.Timer(1, active=True)
            
            with gr.Row():
                with gr.Column():
                    enc_time_plot = gr.Plot(label="Encryption Time vs Message Size")
                with gr.Column():
                    dec_time_plot = gr.Plot(label="Decryption Time vs Message Size")
            
            with gr.Row():
                with gr.Column():
                    latency_plot = gr.Plot(label="End-to-End Latency vs Message Size")
                with gr.Column():
                    throughput_plot = gr.Plot(label="Throughput vs Message Size")
            
            with gr.Accordion("📈 Aggregated Analysis (Median ± Std Dev)", open=True):
                with gr.Row():
                    with gr.Column():
                        enc_agg_plot = gr.Plot(label="Encryption Time (Median ± Std)")
                    with gr.Column():
                        dec_agg_plot = gr.Plot(label="Decryption Time (Median ± Std)")
                with gr.Row():
                    with gr.Column():
                        lat_agg_plot = gr.Plot(label="End-to-End Latency (Median ± Std)")
                    with gr.Column():
                        thr_agg_plot = gr.Plot(label="Throughput (Median ± Std)")

            with gr.Accordion("📊 Metrics Table", open=False):
                perf_metrics_df = gr.Dataframe(interactive=False, wrap=True)


            # ---- Planned Testing View ----
        with gr.Tab("Planned Testing"):
            gr.Markdown("## Planned Testing (E2E Benchmark)")
            gr.Markdown("Run the automated benchmark suite to test End-to-End messaging performance. This executes `run_e2e.py` without requiring Alice or Bob to be logged in.")
            
            with gr.Tabs():
                with gr.Tab("Test and Output"):
                    run_test_btn = gr.Button("Run E2E Test", variant="primary")
                    pt_raw_log_state = gr.State("")
                    with gr.Row(equal_height=True):
                        pt_search_box = gr.Textbox(
                            label="Search Test Output",
                            placeholder="Filter test output lines (e.g., 1024, Handshake, ERROR)...",
                            scale=4,
                            container=True
                        )
                        pt_show_warmup = gr.Checkbox(
                            label="Show Warm-up Logs",
                            value=False,
                            scale=1
                        )
                        pt_case_sensitive = gr.Checkbox(
                            label="Case Sensitive",
                            value=False,
                            scale=1
                        )
                        pt_clear_search_btn = gr.Button(
                            "Clear",
                            variant="secondary",
                            scale=1
                        )
                    test_output = gr.Textbox(label="Test Output", interactive=False, lines=15)
                    
                with gr.Tab("Raw Result"):
                    pt_results_df = gr.Dataframe(label="Results", interactive=False, wrap=True)
                    
                with gr.Tab("Performance"):
                    pt_dataframe_state = gr.State(None)
                    with gr.Row():
                        pt_plot_type = gr.Radio(["Line (Aggregated)", "Scatter (Raw)"], label="Plot Type", value="Line (Aggregated)")
                        pt_trendline = gr.Dropdown(["None", "OLS", "LOWESS"], label="Trendline (Scatter only)", value="None")
                        pt_log_x = gr.Checkbox(label="Log X-Axis", value=True)
                        pt_log_y = gr.Checkbox(label="Log Y-Axis", value=False)
                    with gr.Row():
                        pt_enc_img = gr.Plot(label="Encryption Time")
                        pt_dec_img = gr.Plot(label="Decryption Time")
                    with gr.Row():
                        pt_lat_img = gr.Plot(label="End-to-End Latency")
                        pt_thr_img = gr.Plot(label="Throughput")

    # ---- Event wiring ----
    regen_key_btn.click(
        fn=regenerate_key,
        inputs=[raw_crypto_log, session, chatbot],
        outputs=[raw_crypto_log, session, chatbot],
    ).then(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )

    reset_server_btn.click(
        fn=restart_server,
        inputs=[chatbot, raw_crypto_log, session],
        outputs=[chatbot, raw_crypto_log, session],
    ).then(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )

    crypto_search_box.change(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )
    crypto_case_sensitive.change(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )
    crypto_clear_search_btn.click(
        fn=lambda raw_log: ("", raw_log),
        inputs=[raw_crypto_log],
        outputs=[crypto_search_box, crypto_log],
    )

    crypto_log.change(
        fn=None,
        inputs=None,
        outputs=None,
        js="""
        function() {
            setTimeout(function() {
                var el = document.querySelector('#crypto_log_box textarea');
                if (el) {
                    el.scrollTop = el.scrollHeight;
                }
            }, 100);
        }
        """
    )

    login_btn.click(
        fn=login,
        inputs=[identity_dd, session, chatbot],
        outputs=[client_view, chatbot, raw_crypto_log, login_status, session, identity_dd, login_btn, logout_btn],
    ).then(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )

    logout_btn.click(
        fn=logout,
        inputs=[session, chatbot],
        outputs=[client_view, chatbot, raw_crypto_log, login_status, session, identity_dd, login_btn, logout_btn],
    ).then(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )

    send_btn.click(
        fn=send_message,
        inputs=[msg_input, chatbot, raw_crypto_log, session],
        outputs=[msg_input, chatbot, raw_crypto_log, session],
    ).then(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )

    msg_input.submit(
        fn=send_message,
        inputs=[msg_input, chatbot, raw_crypto_log, session],
        outputs=[msg_input, chatbot, raw_crypto_log, session],
    ).then(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )

    refresh_btn.click(
        fn=receive_messages,
        inputs=[chatbot, raw_crypto_log, session],
        outputs=[chatbot, raw_crypto_log, session],
    ).then(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )

    auto_refresh.change(
        fn=lambda active: gr.update(active=active),
        inputs=[auto_refresh],
        outputs=[timer]
    )
    
    timer.tick(
        fn=receive_messages,
        inputs=[chatbot, raw_crypto_log, session],
        outputs=[chatbot, raw_crypto_log, session],
    ).then(
        fn=filter_terminal_output,
        inputs=[raw_crypto_log, crypto_search_box, crypto_case_sensitive],
        outputs=[crypto_log],
    )

    db_auto_refresh.change(
        fn=lambda active: gr.update(active=active),
        inputs=[db_auto_refresh],
        outputs=[db_timer]
    )

    db_timer.tick(
        fn=view_db,
        inputs=[],
        outputs=[db_keys_df, db_msgs_df, perf_metrics_df, enc_time_plot, dec_time_plot, latency_plot, throughput_plot, enc_agg_plot, dec_agg_plot, lat_agg_plot, thr_agg_plot],
    )

    refresh_db_btn.click(
        fn=view_db,
        inputs=[],
        outputs=[db_keys_df, db_msgs_df, perf_metrics_df, enc_time_plot, dec_time_plot, latency_plot, throughput_plot, enc_agg_plot, dec_agg_plot, lat_agg_plot, thr_agg_plot],
    )
    
    perf_auto_refresh.change(
        fn=lambda active: gr.update(active=active),
        inputs=[perf_auto_refresh],
        outputs=[perf_timer]
    )

    perf_timer.tick(
        fn=view_db,
        inputs=[],
        outputs=[db_keys_df, db_msgs_df, perf_metrics_df, enc_time_plot, dec_time_plot, latency_plot, throughput_plot, enc_agg_plot, dec_agg_plot, lat_agg_plot, thr_agg_plot],
    )

    refresh_perf_btn.click(
        fn=view_db,
        inputs=[],
        outputs=[db_keys_df, db_msgs_df, perf_metrics_df, enc_time_plot, dec_time_plot, latency_plot, throughput_plot, enc_agg_plot, dec_agg_plot, lat_agg_plot, thr_agg_plot],
    )


# Planned Testing Interactive Plots
    for control in [pt_plot_type, pt_trendline, pt_log_x, pt_log_y]:
        control.change(
            fn=update_pt_plots,
            inputs=[pt_dataframe_state, pt_plot_type, pt_trendline, pt_log_x, pt_log_y],
            outputs=[pt_enc_img, pt_dec_img, pt_lat_img, pt_thr_img]
        )

    run_test_btn.click(
        fn=run_planned_testing,
        inputs=[pt_search_box, pt_case_sensitive, pt_show_warmup],
        outputs=[pt_raw_log_state, test_output, pt_enc_img, pt_dec_img, pt_lat_img, pt_thr_img, pt_results_df, pt_dataframe_state]
    )
    pt_search_box.change(
        fn=filter_terminal_output,
        inputs=[pt_raw_log_state, pt_search_box, pt_case_sensitive, pt_show_warmup],
        outputs=[test_output],
    )
    pt_case_sensitive.change(
        fn=filter_terminal_output,
        inputs=[pt_raw_log_state, pt_search_box, pt_case_sensitive, pt_show_warmup],
        outputs=[test_output],
    )
    pt_show_warmup.change(
        fn=filter_terminal_output,
        inputs=[pt_raw_log_state, pt_search_box, pt_case_sensitive, pt_show_warmup],
        outputs=[test_output],
    )
    pt_clear_search_btn.click(
        fn=lambda raw_log, show_warmup: ("", filter_terminal_output(raw_log, "", False, show_warmup)),
        inputs=[pt_raw_log_state, pt_show_warmup],
        outputs=[pt_search_box, test_output],
    )

    def on_page_load(request: gr.Request = None):
        target_user = "Alice"
        if request and hasattr(request, "query_params"):
            q_user = request.query_params.get("user") or request.query_params.get("identity")
            if q_user in ["Alice", "Bob"]:
                target_user = q_user
        db_results = view_db()
        return (target_user, *db_results)

    # Fetch data and set default identity on page load
    app.load(
        fn=on_page_load,
        inputs=[],
        outputs=[identity_dd, db_keys_df, db_msgs_df, perf_metrics_df, enc_time_plot, dec_time_plot, latency_plot, throughput_plot, enc_agg_plot, dec_agg_plot, lat_agg_plot, thr_agg_plot],
    )

if __name__ == "__main__":
    import os
    import socket
    env_port = os.environ.get("GRADIO_SERVER_PORT")
    if env_port:
        port = int(env_port)
    else:
        port = 7861
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                print(f"Notice: Port {port} is already in use (e.g., by the Electron app). Falling back to an available port...")
                port = None
    app.launch(server_port=port, allowed_paths=[os.path.abspath("results")])

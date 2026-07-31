import socket
import threading
import struct
import json
import os
import sys
import signal
import pyotp
import smtplib
from email.message import EmailMessage
from datetime import datetime

# Import your stream workers
from video_thread import video_stream_worker
from input_thread import input_stream_worker

import os
from dotenv import load_dotenv

# Automatically loads variables from the .env file into the system environment
load_dotenv()

# Fetch the secrets safely
TOTP_SECRET_KEY = os.getenv("TOTP_SECRET_KEY")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not TOTP_SECRET_KEY or not EMAIL_PASSWORD:
    raise ValueError("Missing secrets! Check your .env file.")

# Email Notification Settings
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
EMAIL_SENDER = "cacenschivlad@gmail.com"
EMAIL_RECEIVER = [
    "cacenschivlad@gmail.com",
    "gabrielacacenschi@gmail.com"            
    ]
# --------------------------------------------

def signal_handler(sig, frame):
    print("\n[!] Force closing AllOverTheWorld server...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
    return local_ip

def send_alert_email(client_ip, client_os):
    """
    Reads the email template from email_template.txt and sends an alert
    in a background thread when a client successfully connects.
    """
    try:
        msg = EmailMessage()
        msg["Subject"] = f"🚨 [AllOverTheWorld] New Successful Connection from {client_ip}"
        msg["From"] = EMAIL_SENDER
        msg["To"] = ", ".join(EMAIL_RECEIVER)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Determine the template path relative to this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(script_dir, "email_template.txt")
        
        # Load and format the template file
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
            
        body = template.format(
            client_ip=client_ip,
            client_os=client_os.upper(),
            timestamp=timestamp
        )
        
        msg.set_content(body)
        
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)
            
        print(f"[Email Alert] Successfully sent AllOverTheWorld login alert for {client_ip}")
    except FileNotFoundError:
        print("[Email Alert Error] Could not find 'email_template.txt'. Alert skipped.")
    except Exception as e:
        print(f"[Email Alert Error] Failed to send notification: {e}")

def authenticate_client(client_socket):
    """
    Verifies the 6-digit Google Authenticator code sent by the client.
    Returns: (is_authenticated: bool, client_os: str)
    """
    MAX_PAYLOAD_SIZE = 1024 
    try:
        raw_msglen = client_socket.recv(4)
        if not raw_msglen or len(raw_msglen) < 4:
            return False, "unknown"
        
        msglen = struct.unpack(">L", raw_msglen)[0]
        if msglen > MAX_PAYLOAD_SIZE:
            return False, "unknown"
            
        raw_data = client_socket.recv(msglen)
        if not raw_data:
            return False, "unknown"
            
        auth_msg = json.loads(raw_data.decode('utf-8'))
        client_code = str(auth_msg.get("token", "")).strip()
        client_os = str(auth_msg.get("client_os", "unknown")).lower()
        
        totp = pyotp.TOTP(TOTP_SECRET_KEY)
        if totp.verify(client_code, valid_window=1):
            return True, client_os
            
    except Exception as e:
        print(f"[Auth Error] Handshake failed: {e}")
        
    return False, "unknown"

def server_listener(port, worker_function, name):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(5)
    
    print(f"[{name}] Listening on port {port}...")
    
    while True:
        client_socket, addr = server.accept()
        client_ip = addr[0]
        print(f"[{name}] Connection attempt from {addr}")
        
        # Perform TOTP handshake and extract client OS
        auth_success, client_os = authenticate_client(client_socket)
        
        if auth_success:
            print(f"[{name}] Auth SUCCESS for {addr} (OS: {client_os.upper()})")
            
            # --- TRIGGER EMAIL ALERT (ONLY ON INPUT SERVER TO PREVENT DUPLICATES) ---
            if name == "Input Server":
                threading.Thread(
                    target=send_alert_email, 
                    args=(client_ip, client_os), 
                    daemon=True
                ).start()
            # -------------------------------------------------------------------------
            
            worker_thread = threading.Thread(
                target=worker_function, 
                args=(client_socket,),
                daemon=True
            )
            worker_thread.start()
        else:
            print(f"[{name}] Auth FAILED for {addr}. Closing socket.")
            client_socket.close()

if __name__ == "__main__":
    local_ip = get_local_ip()
    print("=" * 50)
    print(f"ALLOVERTHEWORLD HOST LAN IPv4: {local_ip}")
    print(f"Run this on your Client PC:")
    print(f"  python client.py {local_ip}")
    print("=" * 50)

    # Input Server on Port 5051
    input_thread = threading.Thread(
        target=server_listener, 
        args=(5051, input_stream_worker, "Input Server"), 
        daemon=True
    )
    input_thread.start()
    
    # Video Server on Port 5050
    server_listener(5050, video_stream_worker, "Video Server")
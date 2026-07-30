import socket
import threading
import struct
import json
import os

import pyotp

# Import the worker functions we already wrote
from video_thread import video_stream_worker
from input_thread import input_stream_worker, recvall
import sys
import signal

def signal_handler(sig, frame):
    print("\n[!] Force closing server...")
    os._exit(0)  # Immediately terminates all daemon threads and sockets

signal.signal(signal.SIGINT, signal_handler)

# The Security Layer: In a real app, you would use a TOTP library (like pyotp) 
# or load this from an environment variable.
TOTP_SECRET_KEY = "NFHTWDWNUU4XIGXEEYNETYHYGOL6XDSE"

def authenticate_client(client_socket):
    """
    Verifies the 6-digit Google Authenticator code sent by the client.
    """
    MAX_PAYLOAD_SIZE = 1024 
    try:
        raw_msglen = client_socket.recv(4)
        if not raw_msglen or len(raw_msglen) < 4:
            return False
        
        msglen = struct.unpack(">L", raw_msglen)[0]
        if msglen > MAX_PAYLOAD_SIZE:
            return False
            
        raw_data = client_socket.recv(msglen)
        if not raw_data:
            return False
            
        auth_msg = json.loads(raw_data.decode('utf-8'))
        client_code = str(auth_msg.get("token", "")).strip()
        
        # Verify against current Unix epoch time
        # valid_window=1 allows codes that expired up to 30s ago to prevent network latency rejections
        totp = pyotp.TOTP(TOTP_SECRET_KEY)
        if totp.verify(client_code, valid_window=1):
            return True
            
    except Exception as e:
        print(f"[Auth Error] Handshake failed: {e}")
        
    return False

def server_listener(port, worker_function, name):
    """
    A generic server loop that listens on a port, authenticates, 
    and hands the socket to a worker thread.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allow immediate port reuse if you restart the script
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # 0.0.0.0 binds to all network interfaces (including your Tailscale IP)
    server.bind(('0.0.0.0', port))
    server.listen(5)
    print(f"[{name}] Listening on port {port}...")
    
    while True:
        client_socket, addr = server.accept()
        print(f"[{name}] Connection attempt from {addr}")
        
        # The Security Gate
        if authenticate_client(client_socket):
            print(f"[{name}] Auth SUCCESS for {addr}")
            
            # Spin up the worker thread (video or input)
            t = threading.Thread(
                target=worker_function, 
                args=(client_socket,), 
                daemon=True
            )
            t.start()
        else:
            print(f"[{name}] Auth FAILED for {addr}. Dropping connection.")
            client_socket.close()
            
def get_local_ip():
    """
    Finds the machine's true local IPv4 address on the LAN/Wi-Fi.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable; no packets are actually transmitted
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
    return local_ip

if __name__ == "__main__":
    local_ip = get_local_ip()
    print("="*50)
    print(f"HOST MACHINE LAN IPv4: {local_ip}")
    print("="*50)
    # Start the Input Server on Port 5001 in the background
    input_thread = threading.Thread(
        target=server_listener, 
        args=(5001, input_stream_worker, "Input Server"), 
        daemon=True
    )
    input_thread.start()
    
    # Start the Video Server on Port 5000 in the main thread
    # (This blocks the main thread from exiting, keeping the app alive)
    server_listener(5000, video_stream_worker, "Video Server")
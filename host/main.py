import socket
import threading
import struct
import json
import os

# Import the worker functions we already wrote
from video_thread import video_stream_worker
from input_thread import input_stream_worker, recvall

# The Security Layer: In a real app, you would use a TOTP library (like pyotp) 
# or load this from an environment variable.
SECRET_TOKEN = "my_secure_mesh_password"

def authenticate_client(client_socket):
    """
    Forces the client to send a JSON auth payload before doing anything else.
    Includes bounds-checking to prevent memory exhaustion DoS attacks.
    """
    # Max size for our {"token": "..."} JSON is tiny. 
    # 1024 bytes is more than generous.
    MAX_PAYLOAD_SIZE = 1024 
    
    try:
        # 1. Read the 4-byte size header
        raw_msglen = recvall(client_socket, 4)
        if not raw_msglen:
            return False
        
        # 2. Unpack the requested size
        msglen = struct.unpack(">L", raw_msglen)[0]
        
        # THE FIX: Bounds checking
        if msglen > MAX_PAYLOAD_SIZE:
            print(f"SECURITY ALERT: Client attempted to send {msglen} bytes. Dropping.")
            return False
            
        # 3. Read the JSON payload safely
        raw_data = recvall(client_socket, msglen)
        if not raw_data:
            return False
            
        # 4. Parse and verify
        auth_msg = json.loads(raw_data.decode('utf-8'))
        if auth_msg.get("token") == SECRET_TOKEN:
            return True
            
    except Exception as e:
        print(f"Auth error: {e}")
        
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

if __name__ == "__main__":
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
import socket
import threading
import struct
import numpy as np
import cv2

import sys
import platform

# --- FORCE WINDOWS TO GIVE NATIVE RESOLUTION (NO DPI BLUR / LAG) ---
if platform.system() == "Windows":
    try:
        import ctypes
        # SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except AttributeError:
        # Fallback for older Windows builds
        ctypes.windll.user32.SetProcessDPIAware()
        
IS_WINDOWS = (platform.system() == "Windows")

if IS_WINDOWS:
    import dxcam
else:
    import mss

def video_stream_worker(client_socket):
    # Quality 78 is the sweet spot for crisp text without choking Wi-Fi bandwidth
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 78]
    
    # 1. Initialize camera inside the worker so every new connection gets a fresh handle
    camera = None
    sct = None
    if IS_WINDOWS:
        camera = dxcam.create(output_color="BGR")
        camera.start(target_fps=60)
    else:
        sct = mss.mss()
        monitor = sct.monitors[1]
    
    try:
        while True:
            # --- 2. GRAB THE FRAME ---
            if IS_WINDOWS:
                # Grab latest frame directly from GPU memory
                frame = camera.get_latest_frame()
                if frame is None:
                    continue  # If screen hasn't updated this microsecond, skip
            else:
                raw_frame = sct.grab(monitor)
                frame = np.array(raw_frame)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            # -------------------------

            # 3. Compress to JPEG
            result, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
            if not result:
                continue
                
            data = encoded_frame.tobytes()
            size = len(data)
            
            # 4. Send size header (4 bytes) + image payload
            client_socket.sendall(struct.pack(">L", size) + data)

    # CATCH WINDOWS ERROR 10053 EXPLICITLY AS A CLEAN DISCONNECT
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
        print("[Video Server] Client disconnected cleanly.")
    except Exception as e:
        print(f"[Video Server] Unexpected stream error: {e}")
    finally:
        # Stop and delete the DXcam instance so the next connection can reuse the GPU
        if IS_WINDOWS and camera is not None:
            try:
                camera.stop()
                del camera
            except Exception:
                pass
                
        # Gracefully shut down the socket before closing to free the Windows TCP port instantly
        try:
            client_socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        client_socket.close()
        print("[Video Server] Socket closed. Ready for new connection.")

# Example usage (setting up the server socket):
def start_host_server(host='0.0.0.0', port=5050):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allow immediate port reuse if the script crashes
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    
    print(f"Waiting for connection on port {port}...")
    
    while True:
        client_socket, addr = server.accept()
        print(f"Connection established from {addr}")
        
        # Spin up the video thread for this client
        video_thread = threading.Thread(
            target=video_stream_worker, 
            args=(client_socket,),
            daemon=True
        )
        video_thread.start()

if __name__ == "__main__":
    start_host_server()
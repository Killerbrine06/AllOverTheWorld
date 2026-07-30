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
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except AttributeError:
        ctypes.windll.user32.SetProcessDPIAware()
        
IS_WINDOWS = (platform.system() == "Windows")

if IS_WINDOWS:
    import dxcam # type: ignore
else:
    import mss

def video_stream_worker(client_socket):
    # With Dirty Rectangles saving 80-95% bandwidth, we can bump quality to 92 for sharp text!
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 92]
    
    camera = None
    sct = None
    if IS_WINDOWS:
        camera = dxcam.create(output_color="BGR")
        camera.start(target_fps=60)
    else:
        sct = mss.mss()
        monitor = sct.monitors[1]
    
    prev_frame = None
    
    try:
        while True:
            # 1. Grab the latest frame
            if IS_WINDOWS:
                curr_frame = camera.get_latest_frame()
                if curr_frame is None:
                    continue
            else:
                raw_frame = sct.grab(monitor)
                curr_frame = cv2.cvtColor(np.array(raw_frame), cv2.COLOR_BGRA2BGR)

            # 2. First frame after connection -> Send Full Screen
            if prev_frame is None:
                x, y = 0, 0
                h, w = curr_frame.shape[:2]
                patch = curr_frame
                prev_frame = curr_frame.copy()
            else:
                # --- DIRTY RECTANGLE DETECTION ---
                # Absolute difference between frames
                diff = cv2.absdiff(curr_frame, prev_frame)
                gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
                
                # Threshold ignores minor GPU/video rendering noise (values under 15)
                _, thresh = cv2.threshold(gray_diff, 15, 255, cv2.THRESH_BINARY)
                
                # Find bounding box coordinates of pixels that changed
                y_indices, x_indices = np.where(thresh > 0)
                
                # If zero pixels changed, skip transmitting entirely!
                if len(y_indices) == 0 or len(x_indices) == 0:
                    continue
                
                x_min, x_max = int(np.min(x_indices)), int(np.max(x_indices))
                y_min, y_max = int(np.min(y_indices)), int(np.max(y_indices))
                
                # Add 2-pixel padding so anti-aliased font edges aren't clipped
                x = max(0, x_min - 2)
                y = max(0, y_min - 2)
                w = min(curr_frame.shape[1] - x, (x_max - x_min) + 4)
                h = min(curr_frame.shape[0] - y, (y_max - y_min) + 4)
                
                patch = curr_frame[y:y+h, x:x+w]
                prev_frame = curr_frame.copy()
                # ---------------------------------

            # 3. Compress ONLY the patch to JPEG
            result, encoded_patch = cv2.imencode('.jpg', patch, encode_param)
            if not result:
                continue
                
            data = encoded_patch.tobytes()
            size = len(data)
            
            # 4. Pack 12-Byte Header: [Size(L), X(H), Y(H), W(H), H(H)] + Patch Bytes
            header = struct.pack(">LHHHH", size, x, y, w, h)
            client_socket.sendall(header + data)

    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
        print("[Video Server] Client disconnected cleanly.")
    except Exception as e:
        print(f"[Video Server] Unexpected stream error: {e}")
    finally:
        if IS_WINDOWS and camera is not None:
            try:
                camera.stop()
                del camera
            except Exception:
                pass
                
        try:
            client_socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        client_socket.close()
        print("[Video Server] Socket closed. Ready for new connection.")

def start_host_server(host='0.0.0.0', port=5050):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    
    print(f"Waiting for connection on port {port}...")
    while True:
        client_socket, addr = server.accept()
        print(f"Connection established from {addr}")
        video_thread = threading.Thread(
            target=video_stream_worker, 
            args=(client_socket,),
            daemon=True
        )
        video_thread.start()

if __name__ == "__main__":
    start_host_server()
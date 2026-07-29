import socket
import threading
import struct
import numpy as np
import cv2
import mss

def video_stream_worker(client_socket):
    """
    Captures the screen, compresses it to JPEG, and streams it over TCP.
    """
    # Set JPEG compression quality (0-100). 
    # Lower is faster and uses less bandwidth, but looks worse.
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]

    with mss.mss() as sct:
        # Get the primary monitor's dimensions
        monitor = sct.monitors[1] 
        print(f"Streaming monitor: {monitor['width']}x{monitor['height']}")

        try:
            while True:
                # 1. Capture the screen (returns a BGRA array)
                raw_img = np.array(sct.grab(monitor))

                # 2. Drop the Alpha (transparency) channel
                # OpenCV handles BGR better for JPEG compression, and Alpha is useless for screen sharing
                frame = cv2.cvtColor(raw_img, cv2.COLOR_BGRA2BGR)

                # 3. Compress the frame to JPEG
                success, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
                if not success:
                    continue

                # Convert the encoded matrix to a flat byte array
                data = encoded_frame.tobytes()

                # 4. Pack the frame size into a 4-byte unsigned integer (Big Endian network byte order)
                # This tells the client exactly how many bytes to read for this specific frame
                size_header = struct.pack(">L", len(data))

                # 5. Send the header followed by the image data
                client_socket.sendall(size_header + data)

        except (ConnectionResetError, BrokenPipeError):
            print("Client disconnected.")
        except Exception as e:
            print(f"Streaming error: {e}")
        finally:
            client_socket.close()

# Example usage (setting up the server socket):
def start_host_server(host='0.0.0.0', port=5000):
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
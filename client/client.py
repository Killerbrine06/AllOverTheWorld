import sys
import socket
import struct
import json
import cv2
import argparse
import numpy as np
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

# Configuration
HOST_IP = '127.0.0.1'  # Replace with the Tailscale IP of your Host
SECRET_TOKEN = "my_secure_mesh_password"

def recvall(sock, n):
    """Helper to reliably receive exactly n bytes."""
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data

class VideoReceiverThread(QThread):
    """
    Runs in the background, receiving JPEG frames, decoding them, 
    and emitting them to the main GUI thread.
    """
    # Signal to safely pass the OpenCV image array to the UI thread
    frame_received = pyqtSignal(np.ndarray)

    def run(self):
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_socket.connect((HOST_IP, 5050))
            
            # Send Authentication Token
            auth_payload = json.dumps({"token": SECRET_TOKEN}).encode('utf-8')
            client_socket.sendall(struct.pack(">L", len(auth_payload)) + auth_payload)

            while True:
                # 1. Read size header
                raw_size = recvall(client_socket, 4)
                if not raw_size:
                    break
                size = struct.unpack(">L", raw_size)[0]
                
                # 2. Read frame payload
                frame_data = recvall(client_socket, size)
                if not frame_data:
                    break
                    
                # 3. Decode JPEG to numpy array
                nparr = np.frombuffer(frame_data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    self.frame_received.emit(frame)
                    
        except Exception as e:
            print(f"Video connection error: {e}")
        finally:
            client_socket.close()


class RemoteDesktopClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mesh Remote Desktop")
        self.resize(1280, 720)
        
        # Setup the video display label
        self.video_label = QLabel(self)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        self.setCentralWidget(self.video_label)
        
        # State variables for coordinate translation
        self.host_width = None
        self.host_height = None
        self.current_pixmap_size = None

        # Setup the Input Socket
        self.input_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect_input_socket()

        # Start the Video Thread
        self.video_thread = VideoReceiverThread()
        self.video_thread.frame_received.connect(self.update_frame)
        self.video_thread.start()
        
        # Enable mouse tracking so we can send movements even without clicking
        self.video_label.setMouseTracking(True)
        self.setMouseTracking(True)

    def connect_input_socket(self):
        """Establishes the connection for the input stream and authenticates."""
        try:
            self.input_socket.connect((HOST_IP, 5051))
            auth_payload = json.dumps({"token": SECRET_TOKEN}).encode('utf-8')
            self.input_socket.sendall(struct.pack(">L", len(auth_payload)) + auth_payload)
        except Exception as e:
            print(f"Failed to connect input socket: {e}")
            
    def closeEvent(self, event):
        """
        Triggered automatically by PyQt when the user clicks the 'X' 
        to close the window.
        """
        print("Shutting down connections...")
        
        # 1. Close the input socket safely
        if hasattr(self, 'input_socket') and self.input_socket:
            try:
                self.input_socket.close()
            except Exception as e:
                print(f"Error closing input socket: {e}")

        # 2. Stop the video receiver thread
        if hasattr(self, 'video_thread') and self.video_thread.isRunning():
            # In PyQt, forcefully terminating threads can cause crashes.
            # Calling quit() tells the thread's event loop to stop cleanly.
            self.video_thread.quit()
            self.video_thread.wait(1000) # Wait up to 1 second for it to finish
            
        event.accept()

    def send_command(self, cmd_dict):
        """Packages a dictionary into JSON with the 4-byte header and sends it."""
        try:
            # Inject the OS info for keyboard mapping
            cmd_dict["client_os"] = "mac" if sys.platform == "darwin" else "windows"
            
            payload = json.dumps(cmd_dict).encode('utf-8')
            header = struct.pack(">L", len(payload))
            self.input_socket.sendall(header + payload)
        except Exception as e:
            print(f"Failed to send command: {e}")

    def update_frame(self, frame):
        """Converts the OpenCV array to a QPixmap and displays it."""
        # Store original resolution for input math later
        self.host_height, self.host_width, _ = frame.shape
        
        # Convert BGR (OpenCV) to RGB (PyQt)
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        
        # Create QImage and convert to QPixmap
        qt_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_img)
        
        # Scale the pixmap to fit the window while keeping aspect ratio
        scaled_pixmap = pixmap.scaled(
            self.video_label.width(),
            self.video_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        self.current_pixmap_size = scaled_pixmap.size()
        self.video_label.setPixmap(scaled_pixmap)

    def translate_coordinates(self, client_x, client_y):
        """Maps a click on the Client GUI to the actual pixels on the Host screen."""
        if not self.host_width or not self.current_pixmap_size:
            return None
            
        lbl_w = self.video_label.width()
        lbl_h = self.video_label.height()
        pix_w = self.current_pixmap_size.width()
        pix_h = self.current_pixmap_size.height()
        
        # Calculate the size of the black bars (letterboxing)
        offset_x = (lbl_w - pix_w) // 2
        offset_y = (lbl_h - pix_h) // 2
        
        # Find where the user clicked relative to the actual image, ignoring the black bars
        img_x = client_x - offset_x
        img_y = client_y - offset_y
        
        # If the click landed outside the video (on the black bars), drop it
        if img_x < 0 or img_x > pix_w or img_y < 0 or img_y > pix_h:
            return None
            
        # Scale the remaining coordinate to the Host's native resolution
        host_x = int(img_x * (self.host_width / pix_w))
        host_y = int(img_y * (self.host_height / pix_h))
        
        return host_x, host_y

    # --- UI Event Interceptors ---

    def mouseMoveEvent(self, event):
        coords = self.translate_coordinates(event.position().x(), event.position().y())
        if coords:
            self.send_command({"action": "move", "x": coords[0], "y": coords[1]})

    def mousePressEvent(self, event):
        coords = self.translate_coordinates(event.position().x(), event.position().y())
        if coords:
            btn = "left" if event.button() == Qt.MouseButton.LeftButton else "right"
            self.send_command({"action": "mouse_down", "button": btn, "x": coords[0], "y": coords[1]})
            
    def mouseReleaseEvent(self, event):
        coords = self.translate_coordinates(event.position().x(), event.position().y())
        if coords:
            btn = "left" if event.button() == Qt.MouseButton.LeftButton else "right"
            self.send_command({"action": "mouse_up", "button": btn, "x": coords[0], "y": coords[1]})

    def _get_key_name(self, event):
        """Helper to map PyQt key events to string names compatible with pynput."""
        special_keys = {
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Shift: "shift",
            Qt.Key.Key_Control: "ctrl",
            Qt.Key.Key_Meta: "cmd",       # Mac Command Key
            Qt.Key.Key_Alt: "alt",
            Qt.Key.Key_Up: "up",          # Arrow Keys
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Delete: "delete"
        }
        if event.key() in special_keys:
            return special_keys[event.key()]
        
        # Standard character key
        text = event.text()
        return text.lower() if text else None
    
    def keyPressEvent(self, event):
        key_name = self._get_key_name(event)
        if key_name:
            self.send_command({"action": "key_down", "key": key_name})

    def keyReleaseEvent(self, event):
        key_name = self._get_key_name(event)
        if key_name:
            self.send_command({"action": "key_up", "key": key_name})

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Mesh Remote Desktop Client")
    parser.add_argument("ip", help="The Tailscale IP address of the Host")
    parser.add_argument("--token", default="my_secure_mesh_password", help="The secret auth token")
    
    # 2. Parse the arguments
    args = parser.parse_args()
    
    # 3. Override the global variables before starting the app
    HOST_IP = args.ip
    # SECRET_TOKEN = args.token
    
    app = QApplication(sys.argv)
    window = RemoteDesktopClient()
    window.show()
    sys.exit(app.exec())
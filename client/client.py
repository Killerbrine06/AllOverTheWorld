import sys
import socket
import struct
import json
import cv2
import argparse
import numpy as np
import os
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, 
    QWidget, QDialog, QLineEdit, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QPainter

# Configuration
HOST_IP = '127.0.0.1'  # Replace with the Tailscale IP of your Host

def recvall(sock, n):
    """Helper to reliably receive exactly n bytes."""
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data

class AuthDialog(QDialog):
    """
    A modal popup dialog that prompts the user for their 6-digit TOTP code.
    """
    def __init__(self, host_ip, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Authentication Required")
        self.setFixedSize(300, 150)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # Instruction label
        label = QLabel(f"Enter 6-digit code for:\n{host_ip}")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        
        # 6-digit input field
        self.code_input = QLineEdit(self)
        self.code_input.setPlaceholderText("123456")
        self.code_input.setMaxLength(6)
        self.code_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Larger font for readability
        font = self.code_input.font()
        font.setPointSize(16)
        self.code_input.setFont(font)
        layout.addWidget(self.code_input)
        
        # OK and Cancel buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        self.auth_code = None

    def validate_and_accept(self):
        """
        Ensures the user entered something before accepting the modal.
        """
        text = self.code_input.text().strip()
        if len(text) != 6 or not text.isdigit():
            QMessageBox.warning(self, "Invalid Input", "Please enter a valid 6-digit numeric code.")
            return
            
        self.auth_code = text
        self.accept()

class VideoReceiverThread(QThread):
    """
    Runs in the background, receiving JPEG patches with 12-byte headers, 
    decoding them, and emitting coordinates + frame to the main GUI thread.
    """
    # Signal: (x, y, width, height, decoded_opencv_patch)
    patch_received = pyqtSignal(int, int, int, int, np.ndarray)
    
    def __init__(self, host_ip, auth_code):
        super().__init__()
        self.host_ip = host_ip
        self.auth_code = auth_code

    def run(self):
        HEADER_SIZE = 12  # 4 bytes size + 2 bytes x + 2 bytes y + 2 bytes w + 2 bytes h
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_socket.connect((self.host_ip, 5050))
            
            # Send Authentication Token
            auth_payload = json.dumps({"token": self.auth_code}).encode('utf-8')
            client_socket.sendall(struct.pack(">L", len(auth_payload)) + auth_payload)

            while True:
                # 1. Read 12-byte header
                raw_header = recvall(client_socket, HEADER_SIZE)
                if not raw_header:
                    break
                
                # 2. Unpack: L = Size (4B), H = Unsigned Short (2B each for x, y, w, h)
                size, x, y, w, h = struct.unpack(">LHHHH", raw_header)
                
                # 3. Read patch payload
                frame_data = recvall(client_socket, size)
                if not frame_data:
                    break
                    
                # 4. Decode JPEG patch to numpy array
                nparr = np.frombuffer(frame_data, np.uint8)
                patch = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if patch is not None:
                    self.patch_received.emit(x, y, w, h, patch)
                    
        except Exception as e:
            print(f"Video connection error: {e}")
        finally:
            client_socket.close()


class RemoteDesktopClient(QMainWindow):
    def __init__(self, host_ip, auth_code):
        super().__init__()
        self.setWindowTitle("Mesh Remote Desktop")
        self.resize(1280, 720)
        self.host_ip = host_ip
        self.auth_code = auth_code
        
        # Setup the video display label
        self.video_label = QLabel(self)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        self.setCentralWidget(self.video_label)
        
        # State variables for coordinate translation & canvas rendering
        self.host_width = None
        self.host_height = None
        self.current_pixmap_size = None
        self.master_canvas = None  # Persistent canvas storing full desktop state

        # Setup the Input Socket
        self.input_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect_input_socket()

        # Start the Video Thread
        self.video_thread = VideoReceiverThread(host_ip=host_ip, auth_code=auth_code)
        self.video_thread.patch_received.connect(self.update_frame)
        self.video_thread.start()
        
        # Enable mouse tracking so we can send movements even without clicking
        self.video_label.setMouseTracking(True)
        self.setMouseTracking(True)

    def connect_input_socket(self):
        """Establishes the connection for the input stream and authenticates."""
        try:
            self.input_socket.connect((self.host_ip, 5051))
            auth_payload = json.dumps({"token": self.auth_code}).encode('utf-8')
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

    def update_frame(self, x, y, w, h, patch):
        """
        Paints incoming delta patches onto a persistent master canvas,
        then scales the canvas smoothly to fit the window.
        """
        # 1. First frame received -> initialize master canvas to native screen resolution
        if self.master_canvas is None:
            self.host_width = w
            self.host_height = h
            self.master_canvas = QPixmap(w, h)
            self.master_canvas.fill(Qt.GlobalColor.black)
        
        # 2. Convert BGR (OpenCV) patch to RGB (PyQt)
        rgb_image = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
        patch_h, patch_w, ch = rgb_image.shape
        bytes_per_line = ch * patch_w
        
        # 3. Convert array patch to QPixmap
        qt_img = QImage(rgb_image.data, patch_w, patch_h, bytes_per_line, QImage.Format.Format_RGB888)
        patch_pixmap = QPixmap.fromImage(qt_img)
        
        # 4. Paint the patch onto our master canvas at coordinates (x, y)
        painter = QPainter(self.master_canvas)
        painter.drawPixmap(x, y, patch_pixmap)
        painter.end()
        
        # 5. Scale the master canvas to match the current window size
        scaled_pixmap = self.master_canvas.scaled(
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

    def wheelEvent(self, event):
        """Intercepts trackpad two-finger scrolling or mouse wheel scrolling."""
        # PyQt6 returns angleDelta in 1/8th of a degree. Standard step is 120 (15 degrees * 8).
        # We divide by 120 to get normal vertical/horizontal scroll steps for pynput.
        delta_x = event.angleDelta().x() / 120.0
        delta_y = event.angleDelta().y() / 120.0
        
        # Only send if there is actual movement
        if delta_x != 0 or delta_y != 0:
            self.send_command({
                "action": "scroll", 
                "dx": delta_x, 
                "dy": delta_y
            })

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
    parser.add_argument("ip", help="The IP address of the Host (Windows machine)")
    parser.add_argument("--code", help="6-digit Google Authenticator code (optional)", default=None)
    args = parser.parse_args()
    
    HOST_IP = args.ip
    
    # 1. MUST initialize QApplication before opening any GUI dialogs or windows
    app = QApplication(sys.argv)
    
    # 2. Determine the auth code: use CLI argument if present, otherwise show popup
    auth_code = args.code
    
    if not auth_code:
        dialog = AuthDialog(host_ip=HOST_IP)
        # .exec() opens the dialog modally and pauses execution until Accepted or Rejected
        result = dialog.exec()
        
        if result == QDialog.DialogCode.Accepted and dialog.auth_code:
            auth_code = dialog.auth_code
        else:
            print("[Client] Authentication cancelled by user. Exiting...")
            sys.exit(0)

    print(f"[Client] Connecting to {HOST_IP} with token...")
    
    # 3. Launch the main Remote Desktop GUI
    window = RemoteDesktopClient(host_ip=HOST_IP, auth_code=auth_code)
    window.show()
    
    sys.exit(app.exec())
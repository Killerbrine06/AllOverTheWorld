import json
import sys
import struct
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key

mouse = MouseController()
keyboard = KeyboardController()
HOST_OS = "mac" if sys.platform == "darwin" else "windows"

# Translation map: Map Mac-specific modifiers to Windows/Linux equivalents
MAC_TO_WIN_MAP = {
    "cmd": "ctrl",         # Mac Command -> Windows Control
    "cmd_l": "ctrl_l",     # Left Command
    "cmd_r": "ctrl_r",     # Right Command
    "alt": "alt",          # Mac Option is typically sent as 'alt' by pynput
    "alt_l": "alt_l",
    "alt_r": "alt_r"
}

WIN_TO_MAC_MAP = {
    "ctrl": "cmd",         # Windows Ctrl -> Mac Command (for copy/paste/shortcuts)
    "ctrl_l": "cmd_l",
    "ctrl_r": "cmd_r",
    "alt": "alt",          # Windows Alt -> Mac Option (pynput treats both as 'alt')
    "alt_l": "alt_l",
    "alt_r": "alt_r"
}

def execute_command(cmd):
    """
    Translates the parsed JSON dictionary into OS-level actions.
    Performs bidirectional keyboard modifier translation between Mac and Win/Linux.
    """
    action = cmd.get("action")
    client_os = cmd.get("client_os", "windows").lower()
    
    if action == "move":
        mouse.position = (cmd.get("x", 0), cmd.get("y", 0))
        
    elif action == "click":
        btn_str = cmd.get("button", "left")
        btn = Button.right if btn_str == "right" else Button.left
        
        if "x" in cmd and "y" in cmd:
            mouse.position = (cmd.get("x"), cmd.get("y"))
        mouse.click(btn, 1)
        
    elif action == "key_press":
        key_val = cmd.get("key")
        
        # --- BIDIRECTIONAL KEYBOARD TRANSLATION ---
        # Case A: Mac Client controlling a Windows/Linux Host
        if client_os == "mac" and HOST_OS == "windows":
            key_val = MAC_TO_WIN_MAP.get(key_val, key_val)
            
        # Case B: Windows/Linux Client controlling a Mac Host
        elif client_os == "windows" and HOST_OS == "mac":
            key_val = WIN_TO_MAC_MAP.get(key_val, key_val)
        # ------------------------------------------
            
        # Execute the keystroke on the Host OS
        if hasattr(Key, key_val):
            special_key = getattr(Key, key_val)
            keyboard.press(special_key)
            keyboard.release(special_key)
        else:
            keyboard.type(key_val)

def recvall(sock, n):
    """
    Helper function to reliably receive exactly n bytes from a TCP socket.
    """
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None  # Connection closed
        data.extend(packet)
    return data

def input_stream_worker(client_socket):
    """
    Listens for 4-byte headers, reads the exact JSON payload safely, 
    and executes it.
    """
    # A single JSON command for mouse/keyboard should never exceed 1-2 KB.
    MAX_COMMAND_SIZE = 2048 
    
    try:
        while True:
            # 1. Read the 4-byte size header
            raw_msglen = recvall(client_socket, 4)
            if not raw_msglen:
                break
            
            # Unpack the integer
            msglen = struct.unpack(">L", raw_msglen)[0]
            
            # THE FIX: Bounds checking
            if msglen > MAX_COMMAND_SIZE:
                print(f"SECURITY ALERT: Payload size {msglen} exceeds limit. Dropping client.")
                break # Break the loop to disconnect the malicious client
            
            # 2. Read the JSON payload safely
            raw_data = recvall(client_socket, msglen)
            if not raw_data:
                break
            
            # Decode bytes to string and parse JSON
            command_str = raw_data.decode('utf-8')
            
            try:
                cmd = json.loads(command_str)
                execute_command(cmd)
            except json.JSONDecodeError:
                print(f"Malformed JSON dropped: {command_str}")

    except (ConnectionResetError, BrokenPipeError):
        print("Input stream disconnected.")
    except Exception as e:
        print(f"Input stream error: {e}")
    finally:
        client_socket.close()
        
import json
import struct
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key

mouse = MouseController()
keyboard = KeyboardController()

# Translation map: Map Mac-specific modifiers to Windows/Linux equivalents
MAC_TO_WIN_MAP = {
    "cmd": "ctrl",         # Mac Command -> Windows Control
    "cmd_l": "ctrl_l",     # Left Command
    "cmd_r": "ctrl_r",     # Right Command
    "alt": "alt",          # Mac Option is typically sent as 'alt' by pynput
    "alt_l": "alt_l",
    "alt_r": "alt_r"
}

def execute_command(cmd):
    """
    Translates the parsed JSON dictionary into OS-level actions.
    Checks the 'client_os' field to translate keyboard modifiers if needed.
    """
    action = cmd.get("action")
    
    # Default to "windows" if the field is missing so old clients don't crash
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
        
        # 1. Translate the key if the client is on a Mac
        if client_os == "mac":
            # If the key is in our dictionary, swap it out. Otherwise, keep it as is.
            key_val = MAC_TO_WIN_MAP.get(key_val, key_val)
            
        # 2. Execute the keystroke
        if hasattr(Key, key_val):
            special_key = getattr(Key, key_val)
            keyboard.press(special_key)
            keyboard.release(special_key)
        else:
            # Standard alphanumeric character
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
    Listens for 4-byte headers, reads the exact JSON payload, and executes it.
    """
    try:
        while True:
            # 1. Read the 4-byte size header
            raw_msglen = recvall(client_socket, 4)
            if not raw_msglen:
                break
            
            # Unpack the 4 bytes into an integer (Big Endian)
            msglen = struct.unpack(">L", raw_msglen)[0]
            
            # 2. Read exactly 'msglen' bytes for the JSON payload
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
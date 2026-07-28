import json
import struct
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key

mouse = MouseController()
keyboard = KeyboardController()

def execute_command(cmd):
    """
    Translates the parsed JSON dictionary into OS-level actions.
    """
    action = cmd.get("action")
    
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
# AllOverTheWorld

**AllOverTheWorld** is a high-performance, multithreaded remote desktop application written entirely in Python. Designed for developers and power users, it focuses on responsive input handling and clean UI delta updates over heavy lossy video encoding.

Many standard remote desktop solutions rely on continuous, lossy H.264 video streams that can introduce noticeable compression artifacts around fine UI elements and text. To improve text legibility and minimize unnecessary bandwidth consumption, AllOverTheWorld implements a custom **"Dirty Rectangles" delta streaming pipeline** utilizing PNG compression for UI updates. Combined with a dual-socket architecture, it ensures that demanding graphical workloads do not bottleneck time-sensitive keyboard and mouse inputs.

## 🚀 Architecture & Features

### 1. Core Architecture & Networking
The application employs a robust multithreaded client-server model utilizing dual raw TCP sockets:
- **Port 5050 (Video):** Dedicated entirely to the high-bandwidth video payload pipeline using a custom binary protocol.
- **Port 5051 (Input):** A lightweight, isolated stream exclusively for serialized JSON input commands.

This separation guarantees that heavy image payloads never block or delay time-sensitive mouse and keyboard interrupts. The socket architecture features robust connection handling, including explicit graceful tear-downs and strict `TIME_WAIT` management. This design safely cleans up resources and prevents DirectX GPU deadlocks upon abrupt client disconnections.

#### Protocol Design Trade-Off: Binary Structs vs. Serialized JSON
The divergence in wire formats reflects a deliberate systems design decision balancing **throughput** against **structural flexibility**:
- **Custom Binary Header on Port 5050 (Speed & Determinism):** Operating at up to 60 FPS, the video pipeline cannot afford serialization overhead or memory allocations in the hot path. A fixed 12-byte C-struct header (`struct.pack('>LHHHH', size, x, y, w, h)`) enables immediate parsing in constant time, allowing the client to slice raw PNG bytes directly into OpenCV decoding buffers with zero string-decoding overhead.
- **Length-Prefixed JSON on Port 5051 (Structural Flexibility & Extensibility):** While inputs require minimal bandwidth, event payloads are heterogeneous—ranging from continuous coordinate updates (`x, y`), two-axis trackpad scroll vectors (`dx, dy`), to key state transitions carrying OS modifier metadata. A 4-byte length-prefixed JSON format allows schema polymorphism and cross-platform flexibility without the maintenance burden of rigid binary bitmasks.

### 2. Delta Streaming ("Dirty Rectangles")
To reduce video compression artifacts and improve text clarity compared to standard lossy feeds, the pipeline transmits selective delta patches:
- **Hardware-Accelerated Frame Grabbing:** Utilizes `dxcam` to pull raw frames directly from the Windows GPU via the Desktop Duplication API (DXGI) in under 4ms.
- **Delta Computation:** Computes precise delta frames between the current and previous frames using `cv2.absdiff` and NumPy.
- **Efficient Encoding:** Extracts only the modified pixels (the "Dirty Rectangle") and encodes them using a mathematically lossless PNG compression algorithm (`cv2.IMWRITE_PNG_COMPRESSION=2`).
- **Custom Binary Protocol:** Transmits the delta patches over the wire using a highly optimized, custom 12-byte binary header structure (`[Size, X, Y, Width, Height]`).

### 3. Cross-Platform Client & Hardware Translation
The client application, built with **PyQt6**, is fully cross-platform. While the primary use case and testing environment involves streaming a Windows Host to a macOS Retina Display Client, the application works seamlessly between two Windows machines.
- **Bidirectional Hardware Mapping:** Automatically translates OS-specific hardware keystrokes and inputs, intelligently mapping macOS trackpad gestures and `Cmd` / `Option` keys to their exact Windows equivalents.
- **Dynamic Letterboxing:** Performs precise visual letterboxing offset calculations on the fly, ensuring that mouse coordinate translations and clicks remain perfectly accurate regardless of the client window's aspect ratio or resolution.

### 4. Dual-Layer Security & Authentication
Security is integrated directly at the socket handshake level:
- **Time-Based Authentication:** Strict Time-Based One-Time Password (TOTP via Google Authenticator/Base32) validation is required during the initial JSON socket handshake. Invalid tokens result in immediate socket termination.
- **Asynchronous Alerts:** A detached, asynchronous background thread intercepts successful authentications and instantly dispatches an SMTP email alert containing connection metadata (Client IP and OS), ensuring real-time auditability without blocking the main event loop.

## 💻 Tech Stack

- **Core:** Python 3.10+
- **Client GUI:** PyQt6
- **Video Pipeline:** OpenCV (`cv2`), NumPy, `dxcam` (Windows DXGI), `mss` (macOS/Linux)
- **Input Handling:** `pynput`
- **Security & Networking:** Raw TCP Sockets, `pyotp` (Google Authenticator), `smtplib`

## ⚙️ Installation & Setup

### Prerequisites
1. Ensure you have Python 3.10 or higher installed.
2. Clone this repository to both your Host and Client machines.

### Host Machine (Windows Server)
1. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
2. Generate your secure TOTP secret:
   ```bash
   python host/setup_auth.py
   ```
   *Scan the generated QR code with Google Authenticator and add the printed Base32 secret to your `.env` file.*
3. Configure your `.env` file (create `host/.env`):
   ```env
   TOTP_SECRET_KEY=your_generated_secret
   EMAIL_PASSWORD=your_app_specific_email_password
   EMAIL_SENDER=sender_email@gmail.com
   EMAIL_RECEIVER=receiver1@gmail.com, receiver2@gmail.com
   ```
   *(Note: `EMAIL_RECEIVER` accepts a single address or a comma-separated list of recipient emails).*
4. Start the Host Server:
   ```bash
   python host/main.py
   ```

### Client Machine (macOS / Windows)
1. Install client requirements:
   ```bash
   pip install PyQt6 opencv-python numpy
   ```
2. Launch the Client GUI:
   ```bash
   python client/client.py <HOST_IP_ADDRESS>
   ```
3. Enter your 6-digit Google Authenticator code in the PyQt6 prompt to establish the connection.

## 🔒 Security

Currently, the application relies on raw TCP sockets which transmit data in plaintext following the initial TOTP authentication. It is highly recommended to run this tool over a secure, encrypted LAN or a VPN/Mesh network.

## 🗺️ Future Roadmap

- **WAN Streaming & Overlay Networks:** Wide Area Network (WAN) streaming and remote internet access are **not yet implemented** but are explicitly planned for the future roadmap. Native integration with overlay networks such as **Tailscale** or **WireGuard** will be added to provide secure, zero-configuration remote access over the internet.
- **End-to-End Encryption:** Transitioning raw TCP sockets to TLS/SSL encrypted streams to eliminate the reliance on VPNs for secure transport.
- **Audio Streaming:** Implementing a low-latency PCM audio forwarding pipeline.


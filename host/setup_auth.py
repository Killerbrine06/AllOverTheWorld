# setup_auth.py
import pyotp
import qrcode

# 1. Generate a permanent Base32 secret key
secret = pyotp.random_base32()

print("=" * 60)
print(f"YOUR NEW TOTP SECRET KEY: {secret}")
print("=" * 60)
print("1. Copy the secret string above into your main.py file.")
print("2. Open Google Authenticator on your phone.")
print("3. Scan the 'authenticator_qr.png' image generated in this folder.")
print("=" * 60)

# 2. Build the provisioning URI
uri = pyotp.totp.TOTP(secret).provisioning_uri(
    name="Windows-Host-PC", 
    issuer_name="AllOverTheWorld"
)

# 3. Save as a QR code image
img = qrcode.make(uri)
img.save("authenticator_qr.png")
import network
import socket
import time
from machine import I2C, Pin
from ads1x15 import ADS1115

# === Wi-Fi Setup ===
SSID = "Detroit"
PASSWORD = "churrospeak"

UDP_IP = "0.0.0.0"   # Listen on all interfaces
UDP_PORT = 5005      # Pico listens here
REPLY_PORT = 5006    # Replies go back to host

# === Setup I2C + ADS1115 ===
i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
adc = ADS1115(i2c, address=0x48, gain=1)

# === Connect to Wi-Fi ===
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(SSID, PASSWORD)

print("🔌 Connecting to Wi-Fi...")
while not wlan.isconnected():
    time.sleep(0.1)

host_ip = wlan.ifconfig()[0]
print("✅ Connected! Pico IP:", host_ip)

# === UDP Socket Setup ===
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(1)  # non-blocking receive with timeout

print(f"📡 Listening on {UDP_IP}:{UDP_PORT}")

def read_sensor():
    raw = adc.read(4, 2, 3)  # rate=4 (1600 SPS), AIN2 vs AIN3
    voltage = adc.raw_to_v(raw)
    return voltage

print("📥 Pico listening and replying to messages")

while True:
    try:
        data, addr = sock.recvfrom(1024)  # receive UDP packet
        msg = data.decode().strip()        # MicroPython decode: no errors keyword

        # Read sensor and append to message
        sensor_value = read_sensor()
        reply = f"{msg} Voltage: {sensor_value}"

        # Send reply explicitly to host on port 5006
        sock.sendto(reply.encode(), (addr[0], REPLY_PORT))

        print("📥 Got:", msg, " | 📤 Sent:", reply)

    except OSError:  # timeout, just loop
        continue
    except Exception as e:
        print("❌ Error:", e)
        break


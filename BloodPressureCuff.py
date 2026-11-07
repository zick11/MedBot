import asyncio
import struct
from bleak import BleakClient, BleakScanner
import requests

# Standard GATT UUIDs for Bluetooth SIG Blood Pressure Service
BP_SERVICE_UUID = "00001810-0000-1000-8000-00805f9b34fb"
BP_MEASUREMENT_CHAR_UUID = "00002a35-0000-1000-8000-00805f9b34fb"

# Local Flask API endpoint on your Raspberry Pi 5
FLASK_API_URL = "http://localhost:5000/api/vitals"


def parse_ieee_11073_sfloat(byte_data):
  """Decodes a 16-bit IEEE-11073 SFLOAT value into a float."""
  raw = int.from_bytes(byte_data, byteorder="little", signed=False)
  mantissa = raw & 0x0FFF
  exponent = (raw & 0xF000) >> 12

  # Sign extension for 12-bit mantissa and 4-bit exponent
  if exponent >= 0x08:
    exponent -= 0x10
  if mantissa >= 0x0800:
    mantissa -= 0x1000

  return round(float(mantissa) * (10**exponent), 1)


def parse_omron_bp_packet(data: bytearray):
  """Dynamically parses the GATT Blood Pressure Measurement (0x2A35) packet.

  Omron Platinum sends dynamic flag bytes indicating which optional fields
  (Timestamp, Pulse Rate, User ID, Status) are present.
  """
  if len(data) < 7:
    raise ValueError("Packet payload too short for Blood Pressure Measurement")

  flags = data[0]

  # Bit 0: Units (0 = mmHg, 1 = kPa)
  unit_is_kpa = bool(flags & 0x01)
  # Bit 1: Time Stamp Present
  timestamp_present = bool(flags & 0x02)
  # Bit 2: Pulse Rate Present
  pulse_present = bool(flags & 0x04)
  # Bit 3: User ID Present
  user_id_present = bool(flags & 0x08)
  # Bit 4: Measurement Status Present
  status_present = bool(flags & 0x10)

  # Read Systolic & Diastolic (bytes 1-4)
  systolic = parse_ieee_11073_sfloat(data[1:3])
  diastolic = parse_ieee_11073_sfloat(data[3:5])

  # Skip Mean Arterial Pressure (bytes 5-6)
  offset = 7

  if unit_is_kpa:
    systolic = round(systolic * 7.50062, 1)
    diastolic = round(diastolic * 7.50062, 1)

  # Skip Timestamp if present (7 bytes: YYYY-MM-DD HH:MM:SS)
  if timestamp_present:
    offset += 7

  # Parse Pulse Rate if present
  pulse_rate = None
  if pulse_present and len(data) >= (offset + 2):
    pulse_rate = parse_ieee_11073_sfloat(data[offset : offset + 2])
    offset += 2

  user_id = None
  if user_id_present and len(data) >= (offset + 1):
    user_id = data[offset]
    offset += 1

  return {
      "systolic": int(systolic),
      "diastolic": int(diastolic),
      "pulse": int(pulse_rate) if pulse_rate else None,
      "user_id": user_id,
  }


def indication_handler(sender, data: bytearray):
  """Callback triggered when the Omron Platinum sends an indication packet."""
  print(f"\n[BLE] Received measurement indication from Omron Cuff: {sender}")

  try:
    readings = parse_omron_bp_packet(data)
    print(
        f"Parsed Readings -> Systolic: {readings['systolic']} mmHg,"
        f" Diastolic: {readings['diastolic']} mmHg, Heart Rate:"
        f" {readings['pulse']} BPM"
    )

    # Payload matching your Flask server schema
    payload = {
        "device_id": f"Omron_Platinum_User_{readings['user_id'] or '1'}",
        "systolic": readings["systolic"],
        "diastolic": readings["diastolic"],
        "heart_rate": readings["pulse"],
    }

    # POST to local Flask database API
    res = requests.post(FLASK_API_URL, json=payload, timeout=5)
    if res.status_code == 201:
      print("[API] Stored Omron vitals successfully into SQLite database!")
    else:
      print(f"[API Error] Failed to store vitals: {res.text}")

  except Exception as e:
    print(f"[Parsing Error]: {e}")


async def main():
  print("Scanning for Omron Platinum Blood Pressure Monitor...")

  # Search specifically by name or Blood Pressure GATT service
  target_device = None
  discovered_devices = await BleakScanner.discover(timeout=8.0)

  for d in discovered_devices:
    device_name = (d.name or "").lower()
    advertised_uuids = [
        u.lower() for u in (d.metadata.get("uuids") or []) if u
    ]

    if "omron" in device_name or BP_SERVICE_UUID.lower() in advertised_uuids:
      target_device = d
      break

  if not target_device:
    print(
        "\nDevice not found! Make sure your Omron Platinum is turned ON and in"
        " Bluetooth transfer mode (press the Bluetooth/Sync button until 'P' or"
        " connection lines flash on the screen)."
    )
    return

  print(
      f"Found device: {target_device.name or 'Omron Cuff'} [{target_device.address}]"
  )
  print("Connecting to Omron Cuff...")

  async with BleakClient(target_device.address) as client:
    if client.is_connected:
      print("Connected! Subscribing to Blood Pressure Indications...")

      # Note: Standard Blood Pressure service uses Indications (start_notify handles both notifications & indications in Bleak)
      await client.start_notify(BP_MEASUREMENT_CHAR_UUID, indication_handler)

      print(
          "Ready! Take a reading on the cuff or press the Sync button to"
          " transfer."
      )

      # Keep the listener connection alive
      try:
        while True:
          await asyncio.sleep(1)
      except asyncio.CancelledError:
        await client.stop_notify(BP_MEASUREMENT_CHAR_UUID)


if __name__ == "__main__":
  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    print("\nProgram stopped.")
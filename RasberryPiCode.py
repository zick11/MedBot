from datetime import datetime
import sqlite3
from flask import Flask, jsonify, request

app = Flask(__name__)
DB_NAME = "vitals_database.db"


def init_db():
  """Initializes the SQLite database to store patient vitals."""
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS vitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            device_id TEXT,
            heart_rate INTEGER,
            hr_status TEXT,
            temperature REAL,
            temp_status TEXT,
            systolic INTEGER,
            diastolic INTEGER,
            bp_status TEXT
        )
    """)
  conn.commit()
  conn.close()


def categorize_heart_rate(hr):
  """Standard resting adult heart rate categories."""
  if hr < 60:
    return "Low (Bradycardia)"
  elif 60 <= hr <= 100:
    return "Normal"
  else:
    return "High (Tachycardia)"


def categorize_temperature(temp_f):
  """Body temperature categories (Fahrenheit)."""
  if temp_f < 95.0:
    return "Low (Hypothermia)"
  elif 95.0 <= temp_f <= 99.1:
    return "Normal"
  elif 99.2 <= temp_f <= 100.3:
    return "Elevated"
  else:
    return "High (Fever)"


def categorize_blood_pressure(systolic, diastolic):
  """AHA standard blood pressure categories."""
  if systolic < 90 or diastolic < 60:
    return "Low (Hypotension)"
  elif systolic < 120 and diastolic < 80:
    return "Normal"
  elif (120 <= systolic <= 129) and (diastolic < 80):
    return "Elevated"
  elif (130 <= systolic <= 139) or (80 <= diastolic <= 89):
    return "High - Stage 1"
  elif systolic >= 140 or diastolic >= 90:
    return "High - Stage 2"
  else:
    return "Hypertensive Crisis"


@app.route("/api/vitals", methods=["POST"])
def receive_vitals():
  data = request.get_json()

  if not data:
    return jsonify({"error": "No JSON payload received"}), 400

  # Extract fields (with default safety checks)
  device_id = data.get("device_id", "Unknown")
  hr = data.get("heart_rate")
  temp = data.get("temperature")  # Expected in Fahrenheit
  systolic = data.get("systolic")
  diastolic = data.get("diastolic")

  # Run categorization logic
  hr_status = categorize_heart_rate(hr) if hr is not None else "N/A"
  temp_status = categorize_temperature(temp) if temp is not None else "N/A"
  bp_status = (
      categorize_blood_pressure(systolic, diastolic)
      if (systolic is not None and diastolic is not None)
      else "N/A"
  )

  timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  # Store in SQLite database
  try:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
            INSERT INTO vitals (timestamp, device_id, heart_rate, hr_status, temperature, temp_status, systolic, diastolic, bp_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp,
            device_id,
            hr,
            hr_status,
            temp,
            temp_status,
            systolic,
            diastolic,
            bp_status,
        ),
    )
    conn.commit()
    conn.close()
  except Exception as e:
    return jsonify({"error": str(e)}), 500

  # Return structured JSON response back to the Pi application/dashboard
  response = {
      "status": "success",
      "timestamp": timestamp,
      "evaluations": {
          "heart_rate": {"value": hr, "category": hr_status},
          "temperature": {"value": temp, "category": temp_status},
          "blood_pressure": {
              "systolic": systolic,
              "diastolic": diastolic,
              "category": bp_status,
          },
      },
  }
  return jsonify(response), 201


@app.route("/api/vitals", methods=["GET"])
def get_vitals_history():
  """Optional endpoint to fetch history for your Pi dashboard UI."""
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT * FROM vitals ORDER BY id DESC LIMIT 50"
  )  # Last 50 readings
  rows = cursor.fetchall()
  conn.close()

  history = []
  for row in rows:
    history.append({
        "id": row[0],
        "timestamp": row[1],
        "device_id": row[2],
        "heart_rate": row[3],
        "hr_status": row[4],
        "temperature": row[5],
        "temp_status": row[6],
        "systolic": row[7],
        "diastolic": row[8],
        "bp_status": row[9],
    })
  return jsonify(history), 200


if __name__ == "__main__":
  init_db()
  # Run on port 5000, accessible locally on the Raspberry Pi
  app.run(host="0.0.0.0", port=5000, debug=True)
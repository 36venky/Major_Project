/**
 * ESP32 ECG WebSocket Client
 * ───────────────────────────
 * Reads raw 12-bit ADC from AD8232 ECG sensor and streams
 * integer values to the Python backend via WebSocket.
 *
 * Sampling rate : 192 Hz  (SAMPLE_INTERVAL = 5208 µs)
 * ADC range     : 0 – 4095  (12-bit)
 * WebSocket path: /ws/device
 * Protocol      : one plain integer string per message, e.g. "2048\n"
 */

#include <WiFi.h>
#include <WebSocketsClient.h>

// ── Network credentials ────────────────────────────────────
const char* ssid     = "OPPO A55";
const char* password = "Kish@2476";

// ── Backend server ─────────────────────────────────────────
// Run `ipconfig` on the PC → "Wireless LAN adapter Wi-Fi" → IPv4 Address
// Update this if your PC's hotspot IP changes.
const char* serverHost = "192.168.43.122";
const int   serverPort = 8000;
const char* wsPath     = "/ws/device";

// ── Hardware ───────────────────────────────────────────────
#define ECG_PIN 36          // GPIO36 (VP) — AD8232 OUTPUT

// ── Sampling ───────────────────────────────────────────────
// 192 Hz  →  1/192 s  =  5208.33 µs  per sample
#define SAMPLING_FREQ      192
#define SAMPLE_INTERVAL_US 5208UL   // microseconds between samples

WebSocketsClient webSocket;

volatile bool wsConnected   = false;
unsigned long lastSampleUs  = 0;

// ── WiFi reconnect ─────────────────────────────────────────
unsigned long lastWifiCheck = 0;
#define WIFI_CHECK_MS 5000

// ── WebSocket event handler ────────────────────────────────
void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      wsConnected = false;
      Serial.println("[WS] Disconnected — will retry in 5 s");
      break;

    case WStype_CONNECTED:
      wsConnected = true;
      Serial.printf("[WS] Connected  ws://%s:%d%s\n",
                    serverHost, serverPort, wsPath);
      break;

    case WStype_TEXT:
      // Backend acknowledgements (not normally sent)
      Serial.printf("[WS] Server: %s\n", (char*)payload);
      break;

    case WStype_ERROR:
      Serial.println("[WS] WebSocket error");
      break;

    case WStype_PING:
      Serial.println("[WS] Ping received");
      break;

    default:
      break;
  }
}

// ── Setup ──────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[BOOT] ECG Guardian — ESP32 Firmware");
  Serial.printf("[BOOT] Sampling rate : %d Hz\n", SAMPLING_FREQ);
  Serial.printf("[BOOT] Sample interval: %lu µs\n", SAMPLE_INTERVAL_US);

  // ADC configuration
  analogReadResolution(12);          // 12-bit: 0–4095
  analogSetAttenuation(ADC_11db);    // full 0–3.3 V range

  // ── Connect to WiFi ─────────────────────────────────────
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.printf("[WiFi] Connecting to '%s'", ssid);

  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - wifiStart > 20000) {
      Serial.println("\n[WiFi] Timeout — restarting");
      ESP.restart();
    }
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.printf("[WiFi] Connected  IP=%s  RSSI=%d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  // ── Connect to WebSocket ─────────────────────────────────
  webSocket.begin(serverHost, serverPort, wsPath);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  // Enable heartbeat: ping every 15 s, timeout after 10 s, 2 retries
  webSocket.enableHeartbeat(15000, 10000, 2);

  Serial.printf("[WS] Connecting to ws://%s:%d%s\n",
                serverHost, serverPort, wsPath);

  lastSampleUs = micros();
}

// ── Loop ───────────────────────────────────────────────────
void loop() {
  // WebSocket must be called every iteration — do NOT put delays here
  webSocket.loop();

  // ── WiFi watchdog: reconnect if dropped ────────────────
  if (millis() - lastWifiCheck >= WIFI_CHECK_MS) {
    lastWifiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi] Lost connection — reconnecting...");
      WiFi.disconnect();
      WiFi.begin(ssid, password);
    }
  }

  // ── Sample ADC at exactly 192 Hz ───────────────────────
  unsigned long now = micros();
  if (now - lastSampleUs >= SAMPLE_INTERVAL_US) {
    lastSampleUs += SAMPLE_INTERVAL_US;   // accumulate — prevents drift

    int ecgValue = analogRead(ECG_PIN);

    // Send to backend if WebSocket is connected
    if (wsConnected) {
      char buf[8];
      itoa(ecgValue, buf, 10);
      webSocket.sendTXT(buf);
    }

    // Always print to Serial for Arduino IDE Serial Monitor / Plotter
    Serial.println(ecgValue);
  }
}

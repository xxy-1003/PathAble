#include <WiFi.h>
#include <WebSocketsServer.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_VL53L0X.h>
#include <ArduinoJson.h>

const char* ssid = "PathAble_Net";
const char* password = "PathAbleSecurePass";

WebSocketsServer webSocket = WebSocketsServer(8081);
Adafruit_MPU6050 mpu;
Adafruit_VL53L0X lox = Adafruit_VL53L0X();

float current_heading = 0.0;
unsigned long last_time = 0;

void setup() {
  Serial.begin(115200);
  Wire.begin();

  // Initialize WiFi AP Mode so phone/laptop can connect directly
  WiFi.softAP(ssid, password);
  Serial.print("AP IP address: ");
  Serial.println(WiFi.softAPIP());

  // Initialize Sensors
  if (!mpu.begin()) { Serial.println("Failed to find MPU6050 chip"); }
  if (!lox.begin()) { Serial.println("Failed to boot VL53L0X"); }

  webSocket.begin();
}

void loop() {
  webSocket.loop();

  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  VL53L0X_RangingMeasurementData_t measure;
  lox.rangingTest(&measure, false);

  // Simple Gyro Integration for Relative Heading
  unsigned long now = millis();
  float dt = (now - last_time) / 1000.0;
  last_time = now;
  current_heading += g.gyro.z * dt * (180.0 / PI);

  int distance_mm = (measure.RangeStatus != 4) ? measure.RangeMilliMeter : -1;

  // Broadcast Telemetry at 20Hz
  StaticJsonDocument<200> doc;
  doc["heading"] = current_heading;
  doc["tof_dist_cm"] = distance_mm / 10.0;
  
  String output;
  serializeJson(doc, output);
  webSocket.broadcastTXT(output);

  delay(50);
}
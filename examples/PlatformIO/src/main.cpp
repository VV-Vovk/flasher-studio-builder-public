#include <Arduino.h>
#include <ArduinoJson.h>
void setup() { Serial.begin(9600); JsonDocument doc; doc["ready"] = true; serializeJson(doc, Serial); }
void loop() {}

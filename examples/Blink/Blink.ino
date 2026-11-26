// Compile-only fixture: a generic MCU board need not have a built-in LED.
void setup() {
#ifdef LED_BUILTIN
  pinMode(LED_BUILTIN, OUTPUT);
#endif
}
void loop() {
#ifdef LED_BUILTIN
  digitalWrite(LED_BUILTIN, HIGH); delay(250);
  digitalWrite(LED_BUILTIN, LOW); delay(250);
#else
  delay(500);
#endif
}

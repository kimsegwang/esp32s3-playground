// XIAO ESP32S3: 1초마다 시리얼로 "hello" 출력 + 내장 LED 토글
// 내장 LED(LED_BUILTIN = GPIO21)는 active-low: LOW = 켜짐

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);  // 꺼진 상태로 시작
}

void loop() {
  static bool ledOn = false;

  ledOn = !ledOn;
  digitalWrite(LED_BUILTIN, ledOn ? LOW : HIGH);
  Serial.println("hello");
  delay(200);
}

// XIAO ESP32S3 Sense: 카메라 MJPEG 스트리밍 + HTTP로 LED 깜빡임 속도 제어
//
// 포트 80
//   GET /            상태 (JSON)
//   GET /capture     JPEG 한 장
//   GET /blink?ms=N  LED 토글 간격을 N ms로 변경 (50~10000)
// 포트 81
//   GET /stream      MJPEG 스트림
//
// 와이파이 정보는 secrets.h (secrets.h.example 참고, 깃에 올리지 않음)
//
// 발열을 줄이기 위해 카메라는 /stream, /capture 요청이 있는 동안에만 켜고, 마지막 요청이 끝나면 끈다.

#include <WiFi.h>
#include <ESPmDNS.h>
#include "esp_camera.h"
#include "esp_http_server.h"
#include "secrets.h"

// XIAO ESP32S3 Sense 카메라 핀 (CameraWebServer 예제의 CAMERA_MODEL_XIAO_ESP32S3)
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  10
#define SIOD_GPIO_NUM  40
#define SIOC_GPIO_NUM  39
#define Y9_GPIO_NUM    48
#define Y8_GPIO_NUM    11
#define Y7_GPIO_NUM    12
#define Y6_GPIO_NUM    14
#define Y5_GPIO_NUM    16
#define Y4_GPIO_NUM    18
#define Y3_GPIO_NUM    17
#define Y2_GPIO_NUM    15
#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM  47
#define PCLK_GPIO_NUM  13

#define MDNS_NAME "esp32cam"  // http://esp32cam.local

#define PART_BOUNDARY "frame"
static const char *STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// HTTP 핸들러(다른 태스크)에서 쓰고 loop()에서 읽는다
static volatile uint32_t blinkMs = 1000;

static httpd_handle_t controlServer = NULL;
static httpd_handle_t streamServer = NULL;

// 카메라를 쓰고 있는 요청 수. 포트 80/81 서버가 서로 다른 태스크라 뮤텍스로 보호
static SemaphoreHandle_t cameraLock = NULL;
static int cameraUsers = 0;

static bool initCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;  // 640x480: 손 인식에 충분하고 와이파이 부담이 적다
  config.jpeg_quality = 12;           // 0~63, 낮을수록 고화질
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;  // 항상 최신 프레임 (지연 최소화)

  if (!psramFound()) {
    Serial.println("PSRAM not found. FQBN에 PSRAM=opi가 있는지 확인");
    return false;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x (카메라 보드 연결 확인)\n", err);
    return false;
  }
  return true;
}

// 첫 사용자가 들어올 때 카메라를 켠다
static bool acquireCamera() {
  bool ok = true;
  xSemaphoreTake(cameraLock, portMAX_DELAY);
  if (cameraUsers == 0) {
    ok = initCamera();
    if (ok) {
      Serial.println("camera on");
    }
  }
  if (ok) {
    cameraUsers++;
  }
  xSemaphoreGive(cameraLock);
  return ok;
}

// 마지막 사용자가 나가면 카메라를 끈다
static void releaseCamera() {
  xSemaphoreTake(cameraLock, portMAX_DELAY);
  if (--cameraUsers == 0) {
    esp_camera_deinit();
    Serial.println("camera off");
  }
  xSemaphoreGive(cameraLock);
}

static esp_err_t statusHandler(httpd_req_t *req) {
  char json[112];
  snprintf(json, sizeof(json), "{\"blink_ms\":%lu,\"rssi\":%d,\"camera_users\":%d}", (unsigned long)blinkMs,
           WiFi.RSSI(), cameraUsers);
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, json);
}

static esp_err_t captureHandler(httpd_req_t *req) {
  if (!acquireCamera()) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    releaseCamera();
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  releaseCamera();
  return res;
}

static esp_err_t blinkHandler(httpd_req_t *req) {
  char query[32];
  char value[12];
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK
      || httpd_query_key_value(query, "ms", value, sizeof(value)) != ESP_OK) {
    httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "usage: /blink?ms=1000");
    return ESP_FAIL;
  }
  long ms = constrain(atol(value), 50, 10000);
  blinkMs = ms;
  Serial.printf("blink -> %ld ms\n", ms);
  return statusHandler(req);
}

static esp_err_t streamHandler(httpd_req_t *req) {
  char part[64];
  esp_err_t res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  if (res != ESP_OK) {
    return res;
  }
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  if (!acquireCamera()) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }

  // 클라이언트가 끊을 때까지 계속 전송
  while (res == ESP_OK) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      res = ESP_FAIL;
      break;
    }
    size_t hlen = snprintf(part, sizeof(part), STREAM_PART, fb->len);
    res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, part, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    }
    esp_camera_fb_return(fb);
  }
  releaseCamera();
  return res;
}

static void startServers() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();

  httpd_uri_t statusUri = {.uri = "/", .method = HTTP_GET, .handler = statusHandler, .user_ctx = NULL};
  httpd_uri_t captureUri = {.uri = "/capture", .method = HTTP_GET, .handler = captureHandler, .user_ctx = NULL};
  httpd_uri_t blinkUri = {.uri = "/blink", .method = HTTP_GET, .handler = blinkHandler, .user_ctx = NULL};
  if (httpd_start(&controlServer, &config) == ESP_OK) {
    httpd_register_uri_handler(controlServer, &statusUri);
    httpd_register_uri_handler(controlServer, &captureUri);
    httpd_register_uri_handler(controlServer, &blinkUri);
  }

  // 스트림은 연결을 계속 붙잡고 있으므로 별도 서버(포트 81)로 분리
  config.server_port = 81;
  config.ctrl_port += 1;
  httpd_uri_t streamUri = {.uri = "/stream", .method = HTTP_GET, .handler = streamHandler, .user_ctx = NULL};
  if (httpd_start(&streamServer, &config) == ESP_OK) {
    httpd_register_uri_handler(streamServer, &streamUri);
  }
}

static void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // 절전 모드는 스트리밍 지연을 키운다
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connecting to %s", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
}

static void printAddress() {
  IPAddress ip = WiFi.localIP();
  Serial.printf("IP: %s  stream: http://%s:81/stream  control: http://%s/blink?ms=1000\n",
                ip.toString().c_str(), ip.toString().c_str(), ip.toString().c_str());
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // 아무도 시리얼을 안 읽어도 loop()가 느려지지 않게
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);  // active-low: 꺼진 상태로 시작

  // 부팅 시 카메라 연결만 확인하고 바로 끈다 (실제 사용은 요청이 올 때)
  if (!initCamera()) {
    // 카메라 실패 시 LED를 빠르게 깜빡여 표시
    while (true) {
      digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
      delay(100);
    }
  }
  esp_camera_deinit();
  cameraLock = xSemaphoreCreateMutex();

  connectWiFi();
  if (MDNS.begin(MDNS_NAME)) {
    MDNS.addService("http", "tcp", 80);
  }
  startServers();
  printAddress();
}

void loop() {
  static bool ledOn = false;
  static uint32_t lastToggle = 0;
  static uint32_t lastPrint = 0;
  uint32_t now = millis();

  if (now - lastToggle >= blinkMs) {
    lastToggle = now;
    ledOn = !ledOn;
    digitalWrite(LED_BUILTIN, ledOn ? LOW : HIGH);
  }

  // 시리얼 모니터를 나중에 열어도 주소를 볼 수 있게 주기적으로 출력
  if (now - lastPrint >= 10000) {
    lastPrint = now;
    printAddress();
  }

  delay(5);
}

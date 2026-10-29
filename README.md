# esp32s3-playground

Seeed Studio **XIAO ESP32S3 Sense**(카메라 포함) 보드로 이것저것 실험하는 레포.
보드 펌웨어는 arduino-cli로 빌드하고, PC 쪽 처리는 파이썬(conda)으로 한다.

## 현재 프로젝트: 손 모양으로 LED 속도 바꾸기

보드 카메라 영상을 와이파이로 PC에 보내고, PC가 MediaPipe로 손 모양을 인식해서 보드 LED 깜빡임 속도를 바꾼다.

```
[ESP32-S3 카메라] ──와이파이 MJPEG──▶ [PC: hand_blink.py]
                                       MediaPipe 손 인식 → 펴진 손가락 판정
[ESP32-S3 LED]   ◀──HTTP /blink?ms=N── 제스처가 바뀌면 전송
```

| 손 모양 | LED 토글 간격 |
|---|---|
| ✊ 주먹 | 200 ms |
| ☝️ 검지 하나 | 1000 ms |
| ✌️ 검지 + 중지 | 2000 ms |

같은 모양이 5프레임 연속 인식돼야 적용된다(오인식 방지).

## 폴더 구조

```
firmware/                ESP32 아두이노 스케치 (폴더명 = .ino 파일명)
  hello_blink/           시리얼 "hello" 출력 + LED 깜빡임 (동작 확인용)
  camera_blink/          카메라 스트림 + HTTP로 LED 속도 제어
    secrets.h.example    와이파이 정보 템플릿
host/                    PC에서 실행하는 파이썬 코드
  environment.yml        conda 환경(esp32cam) 정의
  esp32cam_stream.py     MJPEG 스트림 수신 모듈
  stream_view.py         카메라 영상만 확인
  hand_blink.py          손 인식 → LED 속도 제어
  serial_test.py         pyserial로 시리얼 출력 확인
CLAUDE.md                개발 규칙과 명령어 상세 정리
```

## 준비물

- Seeed Studio XIAO ESP32S3 Sense + 데이터 전송용 USB-C 케이블
- 2.4GHz 와이파이 (ESP32는 5GHz 미지원), PC와 같은 네트워크
- Windows + [arduino-cli](https://arduino.github.io/arduino-cli/) + conda(Miniforge 등)

## 시작하기

### 1. 펌웨어 환경

```powershell
winget install --id ArduinoSA.CLI -e
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

FQBN은 카메라용 PSRAM을 켠 **`esp32:esp32:XIAO_ESP32S3:PSRAM=opi`** 를 쓴다.

### 2. 와이파이 설정

`firmware/camera_blink/secrets.h.example`을 같은 폴더에 `secrets.h`로 복사한 뒤 값을 채운다.
`secrets.h`는 `.gitignore`에 등록돼 있어 커밋되지 않는다.

```cpp
#define WIFI_SSID     "와이파이 이름"
#define WIFI_PASSWORD "비밀번호"   // 개방형이면 ""
```

### 3. 컴파일 + 업로드

```powershell
arduino-cli board list   # 보드 COM 포트 확인 (USB VID 303A)
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi --build-path firmware/camera_blink/build -p COMx --upload firmware/camera_blink
```

### 4. 보드 IP 확인

```powershell
arduino-cli monitor -p COMx -c baudrate=115200
```

`IP: 192.168.x.x ...` 줄이 10초마다 출력된다. 확인 후 Ctrl+C로 모니터를 닫는다(포트를 잡고 있으면 다른 프로그램이 못 씀).

### 5. 파이썬 환경 + 실행

```powershell
conda env create -f host/environment.yml
conda activate esp32cam

python host/stream_view.py 192.168.x.x   # 영상만 확인
python host/hand_blink.py 192.168.x.x    # 손 인식 → LED 제어
```

창에서 `q` / ESC 또는 X로 종료. 손 인식 모델(`host/models/hand_landmarker.task`)은 처음 실행할 때 자동으로 내려받는다.

## 보드 HTTP API (camera_blink)

| 주소 | 설명 |
|---|---|
| `http://<IP>/` | 상태 (`{"blink_ms":1000,"rssi":-60}`) |
| `http://<IP>/capture` | JPEG 한 장 |
| `http://<IP>/blink?ms=N` | LED 토글 간격 변경 (50~10000 ms) |
| `http://<IP>:81/stream` | MJPEG 영상 스트림 (640x480) |

> 인증이 없으므로 같은 네트워크의 누구나 영상과 제어 주소에 접근할 수 있다. 공용 와이파이에서는 켜 두지 말 것.

## 문제 해결

- **업로드 실패**: 시리얼 모니터 등 포트를 잡은 프로그램을 모두 닫는다. 그래도 안 되면 BOOT 버튼을 누른 채 USB를 연결하고 다시 업로드.
- **와이파이 접속이 안 됨**: 2.4GHz인지, SSID/비밀번호가 맞는지 확인.
- **영상이 끊김 / fps 낮음**: 보드를 공유기 가까이 둔다 (`/`의 `rssi`가 -70보다 낮으면 신호가 약한 편).
- **PSRAM not found**: FQBN에 `PSRAM=opi`가 빠졌는지 확인.

더 자세한 규칙과 명령어는 [CLAUDE.md](CLAUDE.md) 참고.

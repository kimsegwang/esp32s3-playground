# esp32s3-playground

Seeed XIAO ESP32S3 Sense(카메라 포함) 펌웨어 + PC 측 파이썬 코드. 개발 환경은 Windows.
앞으로의 작업은 이 문서를 기준으로 한다.

## 보드 / FQBN

- 보드: Seeed Studio XIAO ESP32S3 Sense (ESP32-S3, 8MB Flash, 8MB OPI PSRAM, OV2640/OV3660 카메라)
- 코어: `esp32:esp32` 3.3.12 (보드 매니저 URL: `https://espressif.github.io/arduino-esp32/package_esp32_index.json`)
- **FQBN: `esp32:esp32:XIAO_ESP32S3:PSRAM=opi`**
  - 카메라 프레임 버퍼에 PSRAM이 필요하므로 `PSRAM=opi`는 항상 포함한다 (기본값은 `disabled`).
  - 그 외 옵션은 기본값 사용 (USBMode=hwcdc, CDCOnBoot=default(Enabled), FlashSize=8M, PartitionScheme=default_8MB).
  - 전체 옵션 확인: `arduino-cli board details -b esp32:esp32:XIAO_ESP32S3`
    (arduino-cli에는 `board options` 명령이 없다)
- 내장 LED: `LED_BUILTIN` (GPIO21), **active-low** (LOW = 켜짐)

## COM 포트 확인

```powershell
arduino-cli board list
```

- 이 PC에서 확인된 포트: **COM5** (`USB\VID_303A&PID_1001`). `board list`에는 "ESP32 Family Device"/"Ozobot DRVKit" 등
  다른 보드 이름으로 나오는데, 같은 PID를 공유해서 생기는 표시일 뿐이므로 무시하고 위 FQBN을 지정해서 쓴다.
- XIAO는 `Unknown`으로 표시될 수 있다. 이 PC에는 블루투스 가상 포트(COM3/4/7/8)가 항상 보이므로 그건 무시한다.
- 어느 포트가 보드인지 애매하면 USB VID `303A`(Espressif)로 확인:

```powershell
Get-CimInstance Win32_PnPEntity | Where-Object { $_.DeviceID -match 'VID_303A' } | Select-Object Name, DeviceID
```

- 보드 리셋/부트 모드 진입 시 COM 번호가 바뀔 수 있으니 업로드 전에 다시 확인한다.

## arduino-cli 명령어

arduino-cli는 conda 환경과 무관하게 실행한다 (conda activate 불필요).
설치 위치: `C:\Program Files\Arduino CLI\arduino-cli.exe` (winget `ArduinoSA.CLI`).
아래에서 `<sketch>`는 스케치 이름, `COMx`는 보드 포트.

```powershell
# 컴파일 (빌드 산출물은 스케치 폴더 아래 build/)
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi --build-path firmware/<sketch>/build firmware/<sketch>

# 업로드 (위에서 빌드한 결과물 사용)
arduino-cli upload -p COMx --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi --input-dir firmware/<sketch>/build firmware/<sketch>

# 시리얼 모니터 (115200, 종료는 Ctrl+C)
arduino-cli monitor -p COMx -c baudrate=115200
```

- `arduino-cli monitor`는 표준입력이 닫히면(EOF) 바로 종료된다. Claude처럼 비대화형으로 몇 초만 출력을 확인할 때는
  stdin을 일정 시간 열어 두는 방식으로 실행한다 (약 6초 후 자동 종료, 포트도 해제됨):

```powershell
cmd /c 'ping -n 7 127.0.0.1 >nul | "C:\Program Files\Arduino CLI\arduino-cli.exe" monitor -p COM5 -c baudrate=115200'
```

## 폴더 구조와 이름 규칙

```
firmware/                ESP32 아두이노 스케치
  hello_blink/
    hello_blink.ino        시리얼 "hello" + LED 깜빡임
  camera_blink/
    camera_blink.ino       카메라 MJPEG 스트림(:81/stream) + LED 속도 제어(:80/blink?ms=N)
                           카메라는 /stream·/capture 요청 중에만 켬 (발열 감소, 사용 수는 뮤텍스로 관리)
    secrets.h.example      와이파이 정보 템플릿 → secrets.h로 복사해서 사용
host/                    PC에서 실행하는 파이썬 코드
  environment.yml        conda 환경 정의
  serial_test.py         pyserial로 시리얼 출력 확인
  esp32cam_stream.py     MJPEG 스트림 수신 모듈 (최신 프레임만 유지)
  stream_view.py         카메라 영상 확인
  hand_blink.py          MediaPipe 손 인식 → 주먹 200ms / 검지 1000ms / V 2000ms
  models/                MediaPipe 모델 (자동 다운로드, 깃 제외)
```

- 스케치마다 `firmware/` 아래 하위 폴더를 만들고, **폴더명 = .ino 파일명**으로 맞춘다
  (예: `firmware/hello_blink/hello_blink.ino`).
- 폴더명에는 하이픈(`-`) 대신 **언더스코어(`_`)**를 쓴다.
- 와이파이 정보 등은 스케치 폴더의 `secrets.h`에 두고 커밋하지 않는다 (`.gitignore`에 등록됨).

## 파이썬(host) 규칙

- PC 측 파이썬 코드는 **conda 환경 `esp32cam`(Python 3.11)에서만 실행**한다.
- 패키지 설치·파이썬 실행 시 반드시 이 환경을 사용하고, **base 환경이나 시스템 파이썬에는 절대 설치하지 않는다.**
- 의존성은 `host/environment.yml`에 정리한다 (현재: opencv-contrib-python, pyserial, requests, mediapipe).
  - `opencv-python`은 설치하지 않는다. mediapipe가 설치하는 `opencv-contrib-python`과 같은 `cv2` 폴더를 써서 충돌한다.
  - mediapipe 1.x에는 `mp.solutions`가 없다. 손 인식은 `mediapipe.tasks.python.vision.HandLandmarker`(Tasks API)를 쓴다.
- 영상 창(cv2.imshow)을 띄우는 스크립트는 `conda run -n esp32cam --no-capture-output python ...`으로 실행한다.

```powershell
# 환경 생성 (최초 1회)
conda env create -f host/environment.yml

# environment.yml 변경 후 반영
conda env update -n esp32cam -f host/environment.yml

# 실행 (activate 없이)
conda run -n esp32cam python host/serial_test.py COMx

# 패키지 추가 설치가 필요할 때 (environment.yml에도 추가할 것)
conda run -n esp32cam python -m pip install <package>
```

## 와이파이 / 카메라

- 와이파이 정보는 스케치 폴더의 `secrets.h`(`WIFI_SSID`, `WIFI_PASSWORD`)에 둔다. `secrets.h.example`을 복사해서 만든다.
- ESP32는 **2.4GHz 와이파이만** 지원한다. PC와 같은 네트워크여야 한다.
- 보드 IP는 시리얼 출력의 `IP: ...` 줄로 확인한다 (10초마다 다시 출력됨). mDNS 이름 `esp32cam.local`도 등록한다.
- 시리얼 출력은 `Serial.setTxTimeoutMs(0)`을 넣는다. 안 넣으면 USB로 PC에 연결돼 있는데 아무도 시리얼을 안 읽을 때
  버퍼가 차서 `Serial.print`가 매번 최대 100ms씩 대기하고 loop()가 느려진다.

## 시리얼 포트 사용 주의

- 한 포트는 한 프로그램만 열 수 있다. `arduino-cli monitor`, Arduino IDE 시리얼 모니터, 파이썬 스크립트를 **동시에 실행하지 않는다.**
- 업로드 전에도 포트를 잡고 있는 프로그램을 모두 종료한다.

## 업로드 실패 시 대처법

1. **시리얼 모니터 종료**: arduino-cli monitor / Arduino IDE 시리얼 모니터 / 파이썬 스크립트 등 포트를 잡은 프로그램을 모두 닫는다 (`Access is denied`, `could not open port` 에러의 주원인).
2. **부트로더 모드로 진입**: 보드의 **BOOT 버튼을 누른 채 USB를 연결**한 뒤 버튼을 뗀다.
   - 이때 COM 번호가 바뀔 수 있으니 `arduino-cli board list`로 다시 확인 후 업로드.
   - 업로드 후 자동 실행이 안 되면 RESET 버튼을 한 번 누른다.
3. USB 케이블이 데이터 전송용인지 확인 (충전 전용 케이블이면 포트가 아예 안 잡힌다).

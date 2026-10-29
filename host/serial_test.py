"""ESP32 시리얼 출력을 읽어 확인하는 테스트.

사용법 (conda 환경 esp32cam에서):
    conda run -n esp32cam python host/serial_test.py COM5
    conda run -n esp32cam python host/serial_test.py COM5 --count 5

시리얼 모니터(arduino-cli monitor 등)가 포트를 잡고 있으면 열리지 않으니 먼저 종료할 것.
"""
import argparse
import sys
import time

import serial


def main() -> int:
    parser = argparse.ArgumentParser(description="Read lines from ESP32 serial port")
    parser.add_argument("port", help="COM 포트 (예: COM5)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--count", type=int, default=5, help="읽을 'hello' 줄 수")
    parser.add_argument("--timeout", type=float, default=10.0, help="전체 대기 시간(초)")
    args = parser.parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"포트를 열 수 없음: {e}", file=sys.stderr)
        return 1

    received = 0
    deadline = time.monotonic() + args.timeout
    with ser:
        while received < args.count and time.monotonic() < deadline:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            print(f"[{args.port}] {line}")
            if line == "hello":
                received += 1

    if received < args.count:
        print(f"FAIL: 'hello' {received}/{args.count}회 수신", file=sys.stderr)
        return 1
    print(f"OK: 'hello' {received}회 수신")
    return 0


if __name__ == "__main__":
    sys.exit(main())

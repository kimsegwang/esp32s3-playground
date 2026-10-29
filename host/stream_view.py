"""ESP32 카메라 스트림을 화면에 띄워 확인한다.

사용법 (conda 환경 esp32cam에서):
    conda run -n esp32cam --no-capture-output python host/stream_view.py 192.168.0.23
종료: 영상 창에서 q / ESC 또는 창 닫기(X)
"""
import argparse
import sys
import time

import cv2

from esp32cam_stream import MjpegStream, should_quit, waiting_screen

WINDOW = "esp32cam"


def main() -> int:
    parser = argparse.ArgumentParser(description="View ESP32 camera stream")
    parser.add_argument("host", nargs="?", default="esp32cam.local", help="보드 IP (시리얼 출력의 IP:)")
    args = parser.parse_args()

    url = f"http://{args.host}:81/stream"
    print(f"connecting {url}")
    stream = MjpegStream(url)
    cv2.namedWindow(WINDOW)

    last_id, frames, fps, fps_time = 0, 0, 0.0, time.monotonic()
    try:
        while True:
            frame_id, frame = stream.read()
            if frame is None:
                if stream.error:
                    print(f"waiting... {stream.error}", file=sys.stderr)
                cv2.imshow(WINDOW, waiting_screen(url, stream.error))
                if should_quit(WINDOW):
                    break
                time.sleep(0.5)
                continue
            if frame_id != last_id:
                last_id = frame_id
                frames += 1
                now = time.monotonic()
                if now - fps_time >= 1.0:
                    fps, frames, fps_time = frames / (now - fps_time), 0, now
                view = frame.copy()
                cv2.putText(view, f"{view.shape[1]}x{view.shape[0]}  {fps:.1f} fps", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.imshow(WINDOW, view)
            if should_quit(WINDOW):
                break
    finally:
        stream.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())

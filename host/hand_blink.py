"""ESP32 카메라 영상에서 손가락 모양을 인식해 보드 LED 깜빡임 속도를 바꾼다.

    주먹          -> 200 ms
    검지 1개      -> 1000 ms
    검지+중지 (V) -> 2000 ms

사용법 (conda 환경 esp32cam에서):
    conda run -n esp32cam --no-capture-output python host/hand_blink.py 192.168.0.23
종료: 영상 창에서 q / ESC 또는 창 닫기(X)

손 인식 모델: host/models/hand_landmarker.task (없으면 자동 다운로드)
"""
import argparse
import math
import sys
import threading
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import requests
from mediapipe.tasks.python import BaseOptions, vision

from esp32cam_stream import MjpegStream, should_quit, waiting_screen

WINDOW = "hand_blink"
MODEL_PATH = Path(__file__).parent / "models" / "hand_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")

# 손가락별 (끝마디, 둘째 관절) 랜드마크 번호. 엄지는 판정이 불안정해서 제외
FINGERS = {"index": (8, 6), "middle": (12, 10), "ring": (16, 14), "pinky": (20, 18)}
WRIST = 0

# 펴진 손가락 조합 -> (제스처 이름, 깜빡임 ms)
GESTURES = {
    frozenset(): ("fist", 200),
    frozenset({"index"}): ("one", 1000),
    frozenset({"index", "middle"}): ("two", 2000),
}

STABLE_FRAMES = 5  # 같은 제스처가 이만큼 연속으로 나와야 적용 (오인식 방지)


def ensure_model() -> Path:
    if not MODEL_PATH.exists():
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {MODEL_URL}")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


def extended_fingers(landmarks, width: int, height: int) -> frozenset:
    """끝마디가 둘째 관절보다 손목에서 멀면 펴진 것으로 본다 (손 방향과 무관)."""
    pts = [(lm.x * width, lm.y * height) for lm in landmarks]
    wrist = pts[WRIST]
    return frozenset(name for name, (tip, pip) in FINGERS.items()
                     if math.dist(wrist, pts[tip]) > math.dist(wrist, pts[pip]))


def draw_hand(image, landmarks):
    h, w = image.shape[:2]
    pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
    for conn in vision.HandLandmarksConnections.HAND_CONNECTIONS:
        cv2.line(image, pts[conn.start], pts[conn.end], (0, 200, 255), 2)
    for p in pts:
        cv2.circle(image, p, 3, (255, 255, 255), -1)


class BlinkController:
    """보드에 /blink 요청을 보낸다. 네트워크 대기 때문에 화면이 멈추지 않게 별도 스레드에서 전송."""

    def __init__(self, host: str):
        self.url = f"http://{host}/blink"
        self.current_ms = None
        self.last_error = None

    def set(self, ms: int):
        if ms == self.current_ms:
            return
        self.current_ms = ms
        threading.Thread(target=self._send, args=(ms,), daemon=True).start()

    def _send(self, ms: int):
        try:
            requests.get(self.url, params={"ms": ms}, timeout=2).raise_for_status()
            self.last_error = None
            print(f"blink -> {ms} ms")
        except requests.RequestException as e:
            self.last_error = str(e)
            self.current_ms = None  # 다음 프레임에서 다시 시도
            print(f"blink request failed: {e}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hand gesture -> ESP32 LED blink speed")
    parser.add_argument("host", nargs="?", default="esp32cam.local", help="보드 IP (시리얼 출력의 IP:)")
    args = parser.parse_args()

    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ensure_model())),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
    )
    stream_url = f"http://{args.host}:81/stream"
    stream = MjpegStream(stream_url)
    blink = BlinkController(args.host)
    cv2.namedWindow(WINDOW)

    last_id = 0
    frames, fps, fps_time = 0, 0.0, time.monotonic()
    candidate, candidate_count, applied = None, 0, None
    start = time.monotonic()
    with vision.HandLandmarker.create_from_options(options) as landmarker:
        try:
            while True:
                frame_id, frame = stream.read()
                if frame is None or frame_id == last_id:
                    if frame is None:
                        cv2.imshow(WINDOW, waiting_screen(stream_url, stream.error))
                        if stream.error:
                            print(f"waiting for stream... {stream.error}", file=sys.stderr)
                        time.sleep(0.5)
                    if should_quit(WINDOW):
                        break
                    continue
                last_id = frame_id
                frames += 1
                now = time.monotonic()
                if now - fps_time >= 1.0:
                    fps, frames, fps_time = frames / (now - fps_time), 0, now

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(image, int((time.monotonic() - start) * 1000))

                gesture = None
                view = frame.copy()
                if result.hand_landmarks:
                    landmarks = result.hand_landmarks[0]
                    draw_hand(view, landmarks)
                    fingers = extended_fingers(landmarks, frame.shape[1], frame.shape[0])
                    gesture = GESTURES.get(fingers)

                # 같은 제스처가 연속으로 나올 때만 적용
                if gesture == candidate:
                    candidate_count += 1
                else:
                    candidate, candidate_count = gesture, 1
                if candidate and candidate_count >= STABLE_FRAMES and candidate != applied:
                    applied = candidate
                    blink.set(applied[1])

                seen = gesture[0] if gesture else "-"
                active = f"{applied[0]} ({applied[1]} ms)" if applied else "none"
                cv2.putText(view, f"seen: {seen}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                cv2.putText(view, f"LED: {active}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                cv2.putText(view, f"{fps:.1f} fps", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
                if blink.last_error:
                    cv2.putText(view, "blink request failed", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (0, 0, 255), 2)
                cv2.imshow(WINDOW, view)
                if should_quit(WINDOW):
                    break
        finally:
            stream.close()
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())

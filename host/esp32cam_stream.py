"""ESP32 카메라(firmware/camera_blink)의 MJPEG 스트림을 백그라운드에서 받아 최신 프레임만 유지한다."""
import re
import threading
import time

import cv2
import numpy as np
import requests

_CONTENT_LENGTH = re.compile(rb"Content-Length:\s*(\d+)", re.IGNORECASE)


def should_quit(window: str) -> bool:
    """q/ESC를 눌렀거나 창의 X 버튼으로 닫았으면 True. 창은 미리 cv2.namedWindow로 만들어 둘 것.

    imshow는 창이 없으면 새로 만들기 때문에, X로 닫힌 걸 확인하지 않으면 창이 계속 다시 뜬다.
    """
    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
        return True
    return cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1


class MjpegStream:
    def __init__(self, url: str):
        self.url = url
        self._lock = threading.Lock()
        self._frame = None
        self._frame_id = 0
        self._stop = threading.Event()
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def read(self):
        """(frame_id, BGR 이미지)를 반환. 아직 프레임이 없으면 (0, None)."""
        with self._lock:
            return self._frame_id, self._frame

    def close(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                with requests.get(self.url, stream=True, timeout=(5, 10)) as resp:
                    resp.raise_for_status()
                    self.error = None
                    self._read_parts(resp)
            except requests.RequestException as e:
                self.error = str(e)
                time.sleep(1)  # 보드 재부팅/와이파이 끊김 시 재접속

    def _read_parts(self, resp):
        # 각 파트: \r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: N\r\n\r\n<JPEG N bytes>
        buf = b""
        for chunk in resp.iter_content(chunk_size=8192):
            if self._stop.is_set():
                return
            buf += chunk
            while True:
                header_end = buf.find(b"\r\n\r\n")
                if header_end < 0:
                    break
                match = _CONTENT_LENGTH.search(buf, 0, header_end)
                if not match:
                    buf = buf[header_end + 4:]
                    continue
                start = header_end + 4
                end = start + int(match.group(1))
                if len(buf) < end:
                    break
                jpeg, buf = buf[start:end], buf[end:]
                frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    with self._lock:
                        self._frame = frame
                        self._frame_id += 1

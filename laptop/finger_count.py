"""Smart Table Guide - laptop side.

Counts raised fingers (both hands, 1-10) with OpenCV + MediaPipe Hands and
sends the confirmed party size to the Arduino over USB serial.

Setup:
    pip install opencv-python mediapipe pyserial
    (Uses the MediaPipe Tasks HandLandmarker API, which works on current
    mediapipe releases. The ~8 MB hand model downloads automatically on the
    first run, so the laptop needs internet once.)

Run:
    python finger_count.py --port COM5            (Windows)
    python finger_count.py --port /dev/tty.usbserial-XXXX   (Mac)
    python finger_count.py                        (no Arduino: prints only)

Keys in the video window:
    q = quit    r = reset all tables    1-6 = mark that table free
"""

import argparse
import math
import os
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

try:
    import serial
except ImportError:
    serial = None

HOLD_SECONDS = 2.0      # count must stay the same this long to confirm
COOLDOWN_SECONDS = 5.0  # pause after seating so one group isn't counted twice

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")
CONNECTIONS = [(c.start, c.end) for c in vision.HandLandmarksConnections.HAND_CONNECTIONS]

TIPS = [8, 12, 16, 20]  # index, middle, ring, pinky fingertips
PIPS = [6, 10, 14, 18]  # their middle joints


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def count_fingers(lm):
    """Count raised fingers on one hand from its 21 landmarks."""
    wrist = lm[0]
    n = 0
    # A finger is up when its tip is farther from the wrist than its middle joint.
    for tip, pip in zip(TIPS, PIPS):
        if dist(lm[tip], wrist) > dist(lm[pip], wrist):
            n += 1
    # Thumb is up when its tip is farther from the pinky knuckle than its IP joint.
    # Works for either hand without needing handedness.
    if dist(lm[4], lm[17]) > dist(lm[3], lm[17]) * 1.15:
        n += 1
    return n


def load_landmarker():
    if not os.path.exists(MODEL_PATH):
        print("Downloading hand model (one time)...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    opts = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.7,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    )
    return vision.HandLandmarker.create_from_options(opts)


def draw_hand(frame, lm):
    h, w = frame.shape[:2]
    pts = [(int(p.x * w), int(p.y * h)) for p in lm]
    for a, b in CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (255, 255, 255), 2)
    for p in pts:
        cv2.circle(frame, p, 4, (0, 0, 255), -1)


class Link:
    """Thin wrapper so the script still runs with no Arduino plugged in."""

    def __init__(self, port):
        self.ser = None
        if port and serial:
            self.ser = serial.Serial(port, 115200, timeout=0)
            time.sleep(2)  # Nano resets when the port opens
        elif port:
            print("pyserial not installed - running without Arduino")

    def send(self, msg):
        print(">>", msg)
        if self.ser:
            self.ser.write((msg + "\n").encode())

    def read_lines(self):
        out = []
        if self.ser:
            while self.ser.in_waiting:
                out.append(self.ser.readline().decode(errors="ignore").strip())
        return [line for line in out if line]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="Arduino serial port")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    link = Link(args.port)
    cap = cv2.VideoCapture(args.camera)
    landmarker = load_landmarker()
    start = time.time()

    candidate, since, sent = 0, time.time(), False
    cooldown_until = 0.0
    last_reply = ""

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)  # mirror so it feels natural
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = landmarker.detect_for_video(image, int((time.time() - start) * 1000))

        total = 0
        for hand in res.hand_landmarks:
            draw_hand(frame, hand)
            total += count_fingers(hand)

        now = time.time()
        if now >= cooldown_until:
            if total != candidate:
                candidate, since, sent = total, now, False
                if candidate > 0:
                    link.send(f"C{candidate}")
            elif candidate > 0 and not sent and now - since >= HOLD_SECONDS:
                link.send(f"P{candidate}")
                sent = True
                cooldown_until = now + COOLDOWN_SECONDS

        for reply in link.read_lines():
            last_reply = reply
            print("<<", reply)

        # On-screen debug info
        held = min(now - since, HOLD_SECONDS) if candidate and not sent else 0
        status = "cooldown" if now < cooldown_until else f"hold {held:.1f}s"
        cv2.putText(frame, f"Fingers: {total}  ({status})", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(frame, f"Arduino: {last_reply}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        cv2.imshow("Smart Table Guide", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            link.send("R")
        if ord("1") <= key <= ord("6"):
            link.send(f"F{chr(key)}")

    landmarker.close()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

"""Smart Table Guide - laptop side.

Counts raised fingers (both hands, 1-10) with OpenCV + MediaPipe Hands and
sends the confirmed party size to the Arduino over USB serial. Hold the number
still for 2 seconds to confirm it.

Setup:
    pip install opencv-python mediapipe pyserial pyobjc-framework-AVFoundation
    (Uses the MediaPipe Tasks HandLandmarker API, which works on current
    mediapipe releases. The ~8 MB hand model downloads automatically on the
    first run, so the laptop needs internet once.)

Run:
    python finger_count.py                 (finds the Arduino's USB port itself;
                                            with none plugged in it just prints)
    python finger_count.py --port COM5     (pick the port yourself)

Gestures:
    number held 2 s         = seat a party of that size
    fist held 2 s, then a number   = seat an accessible party (tables 1-2 only)
    thumbs-up held 1 s, then a number = free that table

Sent to the Arduino, one per line (firmware/table_finder/table_finder.ino):
    C<n> = number being shown (ignored)   P<n> = party size   A<n> = accessible party
    F<t> = table t is free again   R = reset all tables + servo to 0 (also sent on exit)
    O = table status, drawn as the panel on the right

Keys in the video window:
    q = quit    r = reset all tables    1-6 = mark that table free
"""

import argparse
import atexit
from collections import Counter, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
import re
import signal
import sys
import threading
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None

HOLD_SECONDS = 2.0      # count must stay the same this long to confirm
COOLDOWN_SECONDS = 5.0  # pause after seating so one group isn't counted twice
SMOOTH_FRAMES = 7       # majority vote over this many frames to kill flicker

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")
CONNECTIONS = [(c.start, c.end) for c in vision.HandLandmarksConnections.HAND_CONNECTIONS]

TIPS = [8, 12, 16, 20]  # index, middle, ring, pinky fingertips
MCPS = [5, 9, 13, 17]   # their knuckles
FINGER_RATIO = 1.3      # finger is up when tip is this x farther from the wrist than its knuckle (curled <1.2, up >1.45)
THUMB_RATIO = 1.4       # thumb is out when tip-to-pinky-knuckle > this x palm width; raise if a tucked thumb counts
THUMB_UP_MARGIN = 0.03  # thumbs-up: tip must be this far (fraction of frame height) above the rest of the hand

FIST_SECONDS = 2.0      # hold a fist this long -> next group is accessible
THUMB_SECONDS = 1.0     # hold a thumbs-up this long -> free mode (then show a table number)
ACCESS_TIMEOUT = 10.0   # accessible mode cancels if no group is seated in this time
FREE_TIMEOUT = 6.0      # free mode cancels if no table number is started in this time
STATUS_RE = re.compile(r"Is table (\d+) in use\? (\d)")
SEATED_RE = re.compile(r"Tables? (\d+)(?:\+(\d+))?$")

DASHBOARD_PORT = 8765
DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")


class Dashboard:
    """Turns Arduino replies into events and serves them with dashboard.html on localhost."""

    def __init__(self):
        self.events = []
        self.pending = deque()   # (party, accessible) waiting for the Arduino's answer

    def sent(self, msg):
        if msg[0] in "PA":
            self.pending.append((int(msg[1:]), msg[0] == "A"))

    def reply(self, line):
        t = int(time.time() * 1000)
        m = SEATED_RE.match(line)
        if m and self.pending:
            party, acc = self.pending.popleft()
            tables = [int(g) for g in m.groups() if g]
            self.events.append({"t": t, "kind": "seat", "party": party, "accessible": acc, "tables": tables})
        elif line == "No table" and self.pending:
            party, acc = self.pending.popleft()
            self.events.append({"t": t, "kind": "full", "party": party, "accessible": acc})
        elif line.startswith("Freed "):
            self.events.append({"t": t, "kind": "free", "tables": [int(line.split()[1])]})
        elif line == "All free":
            self.events.append({"t": t, "kind": "reset"})

    def serve(self):
        dash = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.split("?")[0] == "/events":
                    body, ctype = json.dumps(dash.events).encode(), "application/json"
                elif self.path in ("/", "/index.html"):
                    with open(DASHBOARD_PATH, "rb") as f:
                        body, ctype = f.read(), "text/html; charset=utf-8"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass  # keep the terminal for >> / << lines

        try:
            server = ThreadingHTTPServer(("127.0.0.1", DASHBOARD_PORT), Handler)
        except OSError as e:
            print(f"Dashboard not started ({e}); is another copy running?")
            return
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"Dashboard: http://localhost:{DASHBOARD_PORT}")


def mac_camera_index():
    """Index of the built-in Mac camera, so a nearby iPhone (Continuity Camera) can't grab index 0."""
    try:
        import AVFoundation as av
    except ImportError:
        return 0
    # Same list and order OpenCV builds its indices from: video + muxed devices, sorted by uniqueID.
    devices = (list(av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeVideo))
               + list(av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeMuxed)))
    devices.sort(key=lambda d: str(d.uniqueID()))
    for i, d in enumerate(devices):
        if d.deviceType() == av.AVCaptureDeviceTypeBuiltInWideAngleCamera:
            return i
    return 0


def dist(a, b):
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def fingers_up(lm):
    """[thumb, index, middle, ring, pinky] raised flags for one hand's 21 landmarks."""
    wrist = lm[0]
    # Thumb is out when its tip is well clear of the palm: far from the pinky knuckle
    # compared to the palm width. Tucked ~0.8-1.2, out ~1.8-2.5. Works for either hand.
    up = [dist(lm[4], lm[17]) > THUMB_RATIO * dist(lm[5], lm[17])]
    # A finger is up when its tip is clearly farther from the wrist than its knuckle.
    for tip, mcp in zip(TIPS, MCPS):
        up.append(dist(lm[tip], wrist) > FINGER_RATIO * dist(lm[mcp], wrist))
    return up


def thumb_points_up(img_lm):
    """Thumb tip is the highest point of the hand by a margin (image y grows downward)."""
    others = min(p.y for i, p in enumerate(img_lm) if i not in (3, 4))
    return img_lm[4].y < others - THUMB_UP_MARGIN


def classify(res):
    """One frame -> None (no hands), "fist", "thumb" (thumbs-up) or a finger count."""
    if not res.hand_world_landmarks:
        return None
    # World landmarks are 3D meters, so counting isn't skewed by the 16:9 frame.
    ups = [fingers_up(hand) for hand in res.hand_world_landmarks]
    # Gestures ignore the thumb's spread: in a real fist it wraps across the fingers
    # and often counts as "out", so judge by the four fingers and the thumb's direction.
    if not any(any(u[1:]) for u in ups):
        if len(ups) == 1 and thumb_points_up(res.hand_landmarks[0]):
            return "thumb"
        return "fist"
    return sum(sum(u) for u in ups)


def load_landmarker():
    if not os.path.exists(MODEL_PATH):
        print("Downloading hand model (one time)...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    opts = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        # VIDEO mode tracks hands between frames, so a hand found once stays found
        # (IMAGE mode had to re-win palm detection every frame and kept dropping hand #2).
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.4,
        min_hand_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    return vision.HandLandmarker.create_from_options(opts)


def draw_hand(frame, lm):
    h, w = frame.shape[:2]
    pts = [(int(p.x * w), int(p.y * h)) for p in lm]
    for a, b in CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (255, 255, 255), 2)
    for p in pts:
        cv2.circle(frame, p, 4, (0, 0, 255), -1)


def find_arduino():
    """First USB serial device (Bluetooth ports have no USB vendor id), or None."""
    return next((p.device for p in list_ports.comports() if p.vid is not None), None)


class Link:
    """Thin wrapper so the script still runs with no Arduino plugged in."""

    def __init__(self, port):
        self.ser = None
        self.buf = ""
        if serial and not port:
            port = find_arduino()
            print(f"Arduino found on {port}" if port else "No Arduino found - printing only")
        if port and serial:
            self.ser = serial.Serial(port, 115200, timeout=0)
            time.sleep(2)  # Nano resets when the port opens
            atexit.register(self.home)
        elif port:
            print("pyserial not installed - running without Arduino")

    def send(self, msg, quiet=False):
        if not quiet:
            print(">>", msg)
        if self.ser:
            self.ser.write((msg + "\n").encode())

    def home(self):
        """On exit: free all tables and send the servo back to 0."""
        try:
            self.send("R")
            self.ser.flush()
        except OSError:
            pass  # Arduino already unplugged

    def read_lines(self):
        """Complete lines received so far; a half-arrived line waits for the next call."""
        if not self.ser:
            return []
        self.buf += self.ser.read(self.ser.in_waiting).decode(errors="ignore")
        *lines, self.buf = self.buf.split("\n")
        return [line.strip() for line in lines if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="Arduino serial port (default: auto-detect)")
    ap.add_argument("--camera", type=int, help="camera index (default: built-in Mac camera)")
    args = ap.parse_args()

    # Closing the terminal or `kill` should still run the atexit reset.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))
    link = Link(args.port)
    cap = cv2.VideoCapture(mac_camera_index() if args.camera is None else args.camera)
    if not cap.isOpened():
        raise SystemExit("Camera failed to open. On macOS: System Settings > Privacy & Security > "
                         "Camera > enable your terminal app, then restart it. Or try --camera 1.")
    landmarker = load_landmarker()

    dash = Dashboard()
    dash.serve()

    def act(msg):
        """Send a table-changing command, then ask for the table status panel."""
        link.send(msg)
        dash.sent(msg)
        link.send("O", quiet=True)

    link.send("O", quiet=True)
    tables = {}             # table id -> in use, filled from the Arduino's O replies
    candidate, since, fired = None, time.time(), False
    mode, mode_until = None, 0.0   # None, "access" or "free"
    cooldown_until = 0.0
    last_reply = ""
    recent = deque(maxlen=SMOOTH_FRAMES)
    stamp = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)  # mirror so it feels natural
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        stamp = max(stamp + 1, int(time.monotonic() * 1000))  # must strictly increase
        res = landmarker.detect_for_video(image, stamp)

        for hand in res.hand_landmarks:
            draw_hand(frame, hand)
        recent.append(classify(res))
        token = Counter(recent).most_common(1)[0][0]

        now = time.time()
        # Modes time out, but not while someone is part-way through holding a number.
        if mode and now > mode_until and not isinstance(candidate, int):
            print(f"== {mode} mode timed out")
            mode = None
        hold = {"fist": FIST_SECONDS, "thumb": THUMB_SECONDS}.get(candidate, HOLD_SECONDS)
        if now >= cooldown_until:
            if token != candidate:
                candidate, since, fired = token, now, False
                if isinstance(token, int):
                    link.send(f"C{token}")
                elif token:
                    print(f"-- {token}")  # fist / thumb seen, not yet held long enough
            elif candidate is not None and not fired and now - since >= hold:
                fired = True
                if candidate == "fist":
                    mode, mode_until = "access", now + ACCESS_TIMEOUT
                    print("== accessible mode: show party size")
                elif candidate == "thumb":
                    mode, mode_until = "free", now + FREE_TIMEOUT
                    print("== free mode: show table number")
                elif mode == "free":
                    act(f"F{candidate}")
                    mode = None
                else:
                    act(f"{'A' if mode == 'access' else 'P'}{candidate}")
                    mode = None
                    cooldown_until = now + COOLDOWN_SECONDS

        for reply in link.read_lines():
            m = STATUS_RE.match(reply)
            if m:
                tables[int(m[1])] = m[2] == "1"
                continue
            dash.reply(reply)
            last_reply = reply
            print("<<", reply)

        # On-screen debug info
        held = min(now - since, hold) if candidate is not None and not fired else 0
        status = "cooldown" if now < cooldown_until else f"hold {held:.1f}s"
        cv2.putText(frame, f"Fingers: {token}  ({status})", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(frame, f"Arduino: {last_reply}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        if mode:
            badge = "ACCESSIBLE: show party size" if mode == "access" else "FREE: show table number"
            cv2.putText(frame, f"{badge} ({max(mode_until - now, 0):.0f}s)", (10, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)

        # Table status panel down the right edge.
        w = frame.shape[1]
        if tables:
            cv2.rectangle(frame, (w - 200, 10), (w - 10, 20 + 30 * len(tables)), (0, 0, 0), -1)
        for i, (tid, used) in enumerate(sorted(tables.items())):
            cv2.putText(frame, f"Table {tid}: {'taken' if used else 'free'}", (w - 190, 35 + 30 * i),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255) if used else (0, 255, 0), 2)
        cv2.imshow("Smart Table Guide", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            act("R")
        if ord("1") <= key <= ord("6"):
            act(f"F{chr(key)}")

    landmarker.close()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

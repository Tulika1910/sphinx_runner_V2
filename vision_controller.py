"""
Camera control for the T-Rex game: jump in real life, the dino jumps.

How it works
  1. A background thread reads the webcam and finds your body (MediaPipe pose; shoulders)
     or, if MediaPipe isn't usable, your face (OpenCV).  Result per frame: a height and a size.
  2. JumpDetector learns your standing height while you stand still for ~2 s, then watches how
     far you rise above it.  The rise is measured in body-size units (shoulder widths), so it
     works the same whether you stand close to the camera or far away.
  3. VisionController hands the game Inputs(jump, restart) each frame.  It plays no part in
     the game rules - it is just another controller.

Hand mode (HandBackend + GestureDetector): make a fist, then open your hand - that is a jump.

Start the game with  python game.py  and pick Body jump or Hand gestures in the menu.
"""
import os
import threading
import time
import urllib.request
from dataclasses import dataclass, replace
from math import hypot
from pathlib import Path
from statistics import median
from typing import NamedTuple, Optional

import cv2
import numpy as np

from controllers import Controller, Inputs

BASE = Path(__file__).resolve().parent
MODEL_FILE = BASE / "pose_landmarker_lite.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task")


# =============================================================================
# 1. Jump detection (pure maths - no camera, no pygame)
# =============================================================================
@dataclass
class Tuning:
    """Distances are in 'body-size' units: shoulder widths (pose) or face widths (face)."""
    threshold: float = 0.25       # rise above standing height that counts as a jump
    early_fraction: float = 0.4   # ...or this fraction of it, if you are rising fast:
    early_speed: float = 2.0      #    faster than this many body-sizes per second
    reset_fraction: float = 0.4   # you must come back below this fraction to jump again
    cooldown: float = 0.35        # seconds between two jumps
    calib_seconds: float = 2.0    # stand still this long to calibrate
    stable_range: float = 0.15    # max wobble allowed while calibrating
    max_air_seconds: float = 1.5  # stuck "in the air" longer than this -> re-learn standing height


POSE_TUNING = Tuning(threshold=0.25, early_speed=2.0, stable_range=0.15)
FACE_TUNING = Tuning(threshold=0.70, early_speed=5.0, stable_range=0.50)

CALIBRATING, ARMED, AIRBORNE = "calibrating", "armed", "airborne"


class JumpDetector:
    """Feed it (time, height_px, size_px) per frame via update(); it says when a jump starts."""

    def __init__(self, tuning: Tuning):
        self.cfg = tuning
        self.recalibrate()

    def recalibrate(self, message="Stand still, facing the camera"):
        self.state = CALIBRATING
        self.message = message
        self.calib_progress = 0.0
        self.baseline_y = None
        self.size = None
        self.rise = 0.0           # how far above standing height, in body-size units
        self.up_speed = 0.0
        self._samples = []
        self._prev = None
        self._last_seen = None
        self._last_trigger = -1e9
        self._air_since = 0.0

    @property
    def calibrated(self) -> bool:
        return self.state != CALIBRATING

    def render_lines(self):
        """(standing height, jump line) in picture pixels, for the preview - or None while calibrating."""
        if not self.calibrated:
            return None
        return self.baseline_y, self.baseline_y - self.cfg.threshold * self.size

    # ---------------------------------------------------------------
    def update(self, now: float, obs: Optional[tuple]) -> bool:
        """obs = (height_px, size_px) with y growing downward, or None if nobody was found.
        Returns True on the frame a jump is detected."""
        if obs is None:
            self._on_lost(now)
            return False
        self._last_seen = now
        y, size = obs[0], obs[1]
        if self.state == CALIBRATING:
            self._calibrate(now, y, size)
            return False
        return self._track(now, y, size)

    def _on_lost(self, now):
        self._prev = None
        if self.state == CALIBRATING:
            self._samples.clear()
            self.calib_progress = 0.0
            self.message = "No person found - step back so your shoulders are in view"
        elif self._last_seen is not None and now - self._last_seen > 3.0:
            self.recalibrate("Lost you - stand still to recalibrate")
        else:
            self.message = "Lost tracking for a moment..."

    def _calibrate(self, now, y, size):
        c = self.cfg
        self._samples.append((now, y, size))
        while self._samples and now - self._samples[0][0] > c.calib_seconds:
            self._samples.pop(0)
        span = now - self._samples[0][0]
        ys = [s[1] for s in self._samples]
        sizes = [s[2] for s in self._samples]
        wobble = (max(ys) - min(ys)) / median(sizes)
        if wobble > c.stable_range:
            self.calib_progress = 0.0
            self.message = "Hold still..."
            # drop the older half so we recover quickly once you settle
            self._samples = self._samples[len(self._samples) // 2:]
            return
        self.calib_progress = min(1.0, span / c.calib_seconds)
        self.message = "Hold still..."
        if span >= c.calib_seconds * 0.95 and len(self._samples) >= 10:
            self.baseline_y = median(ys)
            self.size = median(sizes)
            self.state = ARMED
            self.calib_progress = 1.0
            self.message = "Ready - jump!"
            self._prev = None

    def _track(self, now, y, size):
        c = self.cfg
        self.size += (size - self.size) * 0.1               # smooth the body-size estimate
        self.rise = (self.baseline_y - y) / self.size       # positive = higher than standing

        dt = None
        if self._prev is not None:
            pt, py = self._prev
            dt = now - pt
            if dt > 0:
                v = ((py - y) / self.size) / dt
                self.up_speed = 0.5 * self.up_speed + 0.5 * v
        self._prev = (now, y)

        fired = False
        if self.state == ARMED:
            # follow slow posture changes (leaning, stepping a bit closer)
            if dt and abs(self.rise) < 0.5 * c.threshold and abs(self.up_speed) < 0.4 * c.early_speed:
                self.baseline_y += (y - self.baseline_y) * min(1.0, dt / 2.0)
            big = self.rise >= c.threshold
            early = self.rise >= c.early_fraction * c.threshold and self.up_speed >= c.early_speed
            if (big or early) and now - self._last_trigger >= c.cooldown:
                self.state = AIRBORNE
                self._last_trigger = now
                self._air_since = now
                fired = True
            self.message = "Ready - jump!"
        else:  # AIRBORNE
            if self.rise <= c.reset_fraction * c.threshold:
                self.state = ARMED
            elif now - self._air_since > c.max_air_seconds:
                self.baseline_y = y                         # you stayed up: take this as the new normal
                self.state = ARMED
            self.message = "Jump!"
        return fired


@dataclass
class GestureTuning:
    closed: float = 0.30          # openness below this = fist
    open: float = 0.60            # openness above this = open hand
    cooldown: float = 0.30        # seconds between two jumps
    threshold: float = 0.60       # (the preview bar marks this)


GESTURE_TUNING = GestureTuning()


class GestureDetector:
    """Make a fist, then open your hand = jump.  `obs[2]` is how open the hand is (0 fist ... 1 flat)."""

    calibrated = True             # nothing to calibrate
    state = "armed"
    calib_progress = 1.0
    baseline_y = None
    size = 1.0
    up_speed = 0.0

    def __init__(self, tuning: GestureTuning = GESTURE_TUNING):
        self.cfg = tuning
        self.recalibrate()

    def recalibrate(self, message="Show your hand to the camera"):
        self.message = message
        self.rise = 0.0           # openness, shown on the preview bar
        self.armed = False        # becomes True once we have seen a fist
        self._last = -1e9

    def render_lines(self):
        return None

    def update(self, now, obs) -> bool:
        c = self.cfg
        if obs is None:
            self.rise, self.armed = 0.0, False
            self.message = "Show your hand to the camera"
            return False
        openness = obs[2]
        self.rise = openness
        if openness < c.closed:
            self.armed = True
            self.message = "Ready - open your hand to jump!"
            return False
        if openness >= c.open:
            if self.armed and now - self._last >= c.cooldown:
                self.armed = False
                self._last = now
                self.message = "Jump!"
                return True
            if not self.armed:
                self.message = "Make a fist first, then open your hand"
        return False


# =============================================================================
# 2. Body / face finding
# =============================================================================
class Observation(NamedTuple):
    y: float                  # height of the reference point, pixels (down = bigger)
    size: float               # body size in pixels (shoulder width / face width)
    points: list              # [(x, y), ...] for drawing
    extra: float = 0.0        # backend specific (hand openness)


HAND_MODEL_FILE = BASE / "hand_landmarker.task"
HAND_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                  "hand_landmarker/float16/latest/hand_landmarker.task")


def ensure_model(path=MODEL_FILE, url=MODEL_URL, label="pose"):
    if path.exists() and path.stat().st_size > 1_000_000:
        return
    print(f"[vision] Downloading the {label} model once (a few MB)...")
    tmp = path.with_suffix(".part")
    try:
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"couldn't download the {label} model ({e}). "
                           f"Download it manually from {url} and save it as {path.name} "
                           f"next to game.py") from e


class PoseBackend:
    """MediaPipe pose landmarker: tracks both shoulders (and nose / hips for drawing)."""
    name = "pose"
    tuning = POSE_TUNING

    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import vision, BaseOptions
        ensure_model()
        self._mp = mp
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_FILE)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._t0 = time.monotonic()
        self._last_ts = -1

    def process(self, bgr) -> Optional[Observation]:
        h, w = bgr.shape[:2]
        small = cv2.resize(bgr, (320, int(h * 320 / w))) if w > 320 else bgr   # model works at ~256 px anyway
        rgb = np.ascontiguousarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        ts = max(self._last_ts + 1, int((time.monotonic() - self._t0) * 1000))   # must keep increasing
        self._last_ts = ts
        result = self._landmarker.detect_for_video(image, ts)
        if not result.pose_landmarks:
            return None
        lm = result.pose_landmarks[0]
        left, right = lm[11], lm[12]
        if min(left.visibility or 0.0, right.visibility or 0.0) < 0.5:
            return None
        lx, ly, rx, ry = left.x * w, left.y * h, right.x * w, right.y * h
        size = hypot(lx - rx, ly - ry)
        if size < 20:                                       # far too small to measure
            return None
        points = [(lx, ly), (rx, ry)]
        for i in (0, 23, 24):                               # nose, hips: only for the preview
            if (lm[i].visibility or 0.0) >= 0.5:
                points.append((lm[i].x * w, lm[i].y * h))
        return Observation((ly + ry) / 2, size, points)

    def close(self):
        self._landmarker.close()


class HandBackend:
    """MediaPipe hand landmarker.  Measures how open the hand is from the finger joints."""
    name = "hand"
    tuning = None

    FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))        # (fingertip, middle joint)

    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import vision, BaseOptions
        ensure_model(HAND_MODEL_FILE, HAND_MODEL_URL, "hand")
        self._mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(HAND_MODEL_FILE)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._t0 = time.monotonic()
        self._last_ts = -1

    @staticmethod
    def openness(pts) -> float:
        """0 = fist ... 1 = flat open hand.  Compares each fingertip's distance from the wrist with its
        middle joint's: a straight finger has the tip far beyond the joint, a curled one does not."""
        wrist = pts[0]
        total = 0.0
        for tip, joint in HandBackend.FINGERS:
            ratio = hypot(pts[tip][0] - wrist[0], pts[tip][1] - wrist[1]) / \
                max(1e-6, hypot(pts[joint][0] - wrist[0], pts[joint][1] - wrist[1]))
            total += min(max((ratio - 0.85) / (1.20 - 0.85), 0.0), 1.0)
        return total / len(HandBackend.FINGERS)

    def process(self, bgr) -> Optional[Observation]:
        h, w = bgr.shape[:2]
        small = cv2.resize(bgr, (320, int(h * 320 / w))) if w > 320 else bgr
        rgb = np.ascontiguousarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        ts = max(self._last_ts + 1, int((time.monotonic() - self._t0) * 1000))
        self._last_ts = ts
        result = self._landmarker.detect_for_video(image, ts)
        if not result.hand_landmarks:
            return None
        pts = [(p.x * w, p.y * h) for p in result.hand_landmarks[0]]
        palm = hypot(pts[5][0] - pts[17][0], pts[5][1] - pts[17][1])
        return Observation(pts[0][1], max(palm, 1.0), pts, self.openness(pts))

    def close(self):
        self._landmarker.close()


class FaceBackend:
    """OpenCV face detector: lighter and needs no download, but less steady than pose."""
    name = "face"
    tuning = FACE_TUNING

    def __init__(self):
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(path)
        if self._cascade.empty():
            raise RuntimeError("OpenCV's face model file is missing")

    def process(self, bgr) -> Optional[Observation]:
        h, w = bgr.shape[:2]
        f = min(1.0, 320.0 / w)
        gray = cv2.cvtColor(cv2.resize(bgr, (int(w * f), int(h * f))), cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = self._cascade.detectMultiScale(gray, 1.15, 5, minSize=(40, 40))
        if len(faces) == 0:
            return None
        x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
        cx, cy, size = (x + fw / 2) / f, (y + fh / 2) / f, fw / f
        return Observation(cy, size, [(cx, cy)])

    def close(self):
        pass


def make_backend(choice: str):
    if choice in ("auto", "pose"):
        try:
            return PoseBackend()
        except Exception as e:
            if choice == "pose":
                raise SystemExit(f"[vision] Pose tracking unavailable: {e}")
            print(f"[vision] Pose tracking unavailable ({e}).\n[vision] Falling back to face tracking.")
    return FaceBackend()


CAMERA_APIS = {"auto": None, "dshow": getattr(cv2, "CAP_DSHOW", 0), "msmf": getattr(cv2, "CAP_MSMF", 0),
               "any": cv2.CAP_ANY}


def make_hand_backend():
    try:
        return HandBackend()
    except Exception as e:
        raise SystemExit(f"[vision] Hand tracking unavailable: {e}\n"
                         f"It needs MediaPipe (pip install mediapipe) and a one-time model download.")


def open_camera(index: int, api: str = "auto", exposure=None):
    chosen = CAMERA_APIS[api]
    if chosen is None:                                           # auto: DSHOW opens fast on Windows
        chosen = CAMERA_APIS["dshow"] if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, chosen)
    if not cap.isOpened():
        raise SystemExit(f"Couldn't open camera {index}. Close other apps that use the webcam, "
                         f"or try:  python game.py --controller vision --camera 1")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # webcams only give 30 fps in MJPG
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)                              # don't queue old frames (= lag)
    if exposure is not None:
        # Auto-exposure in dim light makes webcams drop to ~15 fps by using long exposures.
        # A fixed short exposure keeps 30 fps (the picture gets darker - add light).
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)                    # 0.25 = manual on most Windows drivers
        cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
    return cap


# =============================================================================
# 3. Camera threads
# =============================================================================
THUMB_H = 150


class CameraWorker(threading.Thread):
    """
    Two threads so the picture is never stale:
      grabber: reads the webcam as fast as it delivers and keeps ONLY the newest frame
      this one: takes the newest frame, finds the body, runs the detector
    If finding the body is slower than the camera, old frames are skipped, not queued
    (queued frames are what makes camera games feel laggy).
    """

    def __init__(self, capture, backend, detector, mirror=True):
        super().__init__(daemon=True)
        self.capture, self.backend, self.detector, self.mirror = capture, backend, detector, mirror
        self.lock = threading.Lock()          # guards detector + counters
        self.triggers = 0                     # how many jumps were detected so far
        self.thumb = None                     # (rgb bytes, (w, h))
        self.error = None
        self.fps = 0.0                        # frames per second actually processed
        self.latency_ms = 0.0                 # camera picture -> jump decision
        self._stop_flag = threading.Event()
        self._cond = threading.Condition()
        self._latest = None                   # (frame, capture time)
        self._latest_id = 0
        self._grabber = threading.Thread(target=self._grab_loop, daemon=True)

    # ---- thread 1: keep the newest frame -------------------------------
    def _grab_loop(self):
        failures = 0
        while not self._stop_flag.is_set():
            ok, frame = self.capture.read()
            if not ok or frame is None:
                failures += 1
                if failures > 30:
                    with self._cond:
                        self.error = "The camera stopped sending pictures"
                        self._cond.notify_all()
                    return
                time.sleep(0.02)
                continue
            failures = 0
            stamp = time.monotonic()
            with self._cond:
                self._latest = (frame, stamp)
                self._latest_id += 1
                self._cond.notify_all()

    # ---- thread 2: find the body, detect jumps -------------------------
    def run(self):
        self._grabber.start()
        last_id, window_start, window_frames = 0, time.monotonic(), 0
        try:
            while not self._stop_flag.is_set():
                with self._cond:
                    self._cond.wait_for(lambda: self._latest_id != last_id or self.error or self._stop_flag.is_set(),
                                        timeout=0.5)
                    if self.error or self._stop_flag.is_set():
                        break
                    if self._latest_id == last_id:
                        continue
                    frame, stamp = self._latest
                    last_id = self._latest_id

                if self.mirror:
                    frame = cv2.flip(frame, 1)
                obs = self.backend.process(frame)
                with self.lock:
                    fired = self.detector.update(stamp, None if obs is None else (obs.y, obs.size, obs.extra))
                    if fired:
                        self.triggers += 1
                    lines = self.detector.render_lines()
                done = time.monotonic()
                self.latency_ms += ((done - stamp) * 1000 - self.latency_ms) * 0.1
                self.thumb = self._render(frame, obs, lines)

                window_frames += 1
                if done - window_start >= 1.0:
                    self.fps = window_frames / (done - window_start)
                    window_start, window_frames = done, 0
        except Exception as e:                                  # never let the thread die silently
            self.error = f"{type(e).__name__}: {e}"

    def _render(self, frame, obs, lines):
        h, w = frame.shape[:2]
        pts = obs.points if obs else []
        for (px, py) in pts:
            cv2.circle(frame, (int(px), int(py)), 5 if len(pts) < 10 else 3, (0, 220, 0), -1)
        if lines:
            baseline_y, jump_line = lines
            cv2.line(frame, (0, int(baseline_y)), (w, int(baseline_y)), (0, 200, 0), 2)    # standing height
            cv2.line(frame, (0, int(jump_line)), (w, int(jump_line)), (0, 140, 255), 2)    # jump line
        tw = int(THUMB_H * w / h)
        small = cv2.resize(frame, (tw, THUMB_H))
        return cv2.cvtColor(small, cv2.COLOR_BGR2RGB).tobytes(), (tw, THUMB_H)

    def snapshot(self):
        with self.lock:
            d = self.detector
            return dict(thumb=self.thumb, state=d.state, message=d.message, rise=d.rise,
                        threshold=d.cfg.threshold, progress=d.calib_progress,
                        calibrated=d.calibrated, triggers=self.triggers,
                        fps=self.fps, latency_ms=self.latency_ms)

    def recalibrate(self):
        with self.lock:
            self.detector.recalibrate()

    def stop(self):
        self._stop_flag.set()
        with self._cond:
            self._cond.notify_all()


# =============================================================================
# 4. The controller the game talks to
# =============================================================================
class VisionController(Controller):
    """mode 'body' = jump in real life, mode 'hand' = fist-then-open-hand gesture."""
    panel_height = 202
    HOLD_SECONDS = 0.40   # keep "jump" pressed this long: if you jump again while the dino is still
                          # landing from the last one, it fires the moment it touches down.
                          # (shorter than the dino's 0.47 s air time, so it can't double-jump)

    def __init__(self, mode="body", camera=0, backend="auto", sensitivity=1.0, camera_api="auto",
                 exposure=None, _capture=None, _backend=None):
        self.mode = mode
        self.name = mode
        if mode == "hand":
            self.backend = _backend or make_hand_backend()
            self.detector = GestureDetector()
            self.hint = "Make a fist, then open your hand to jump     C = reset     D = theme     Esc = menu"
        else:
            self.backend = _backend or make_backend(backend)
            t = self.backend.tuning
            s = max(0.2, float(sensitivity))          # >1 = easier to trigger, <1 = harder
            self.detector = JumpDetector(replace(t, threshold=t.threshold / s, early_speed=t.early_speed / s))
            self.hint = "Jump in front of the camera!     C = recalibrate     D = theme     Esc = menu"
        capture = _capture or open_camera(camera, camera_api, exposure)
        self.worker = CameraWorker(capture, self.backend, self.detector)
        self.worker.start()
        self._seen = 0
        self._jump_until = 0.0
        self._fonts = {}

    # ---- game-facing ---------------------------------------------------
    @property
    def ready(self) -> bool:
        # if the camera died the game falls back to the keyboard instead of freezing
        return self.worker.error is not None or self.worker.snapshot()["calibrated"]

    def poll(self, now) -> Inputs:
        with self.worker.lock:
            n = self.worker.triggers
        fired = n > self._seen
        self._seen = n
        if fired:
            self._jump_until = now + self.HOLD_SECONDS
        return Inputs(jump=now < self._jump_until, restart=fired)

    def update(self, events) -> Inputs:
        import pygame
        for e in events:
            if e.type == pygame.KEYDOWN and e.key == pygame.K_c:
                self.worker.recalibrate()
        cam = self.poll(time.monotonic())
        # the keyboard still works too - handy for testing
        keys = pygame.key.get_pressed()
        kb_jump = bool(keys[pygame.K_SPACE] or keys[pygame.K_UP])
        kb_restart = any(e.type == pygame.KEYDOWN and e.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_RETURN)
                         for e in events)
        return Inputs(jump=cam.jump or kb_jump, restart=cam.restart or kb_restart)

    # ---- preview panel ---------------------------------------------------
    def _font(self, size, bold=False):
        import pygame
        if (size, bold) not in self._fonts:
            self._fonts[(size, bold)] = pygame.font.SysFont("segoeui,helveticaneue,helvetica,arial", size, bold=bold)
        return self._fonts[(size, bold)]

    def draw_overlay(self, screen, theme, rect):
        """Draws inside `rect` (a glass card the game already painted).
        theme = {'fg', 'soft', 'accent', 'track'} colours."""
        import pygame
        snap = self.worker.snapshot()
        x, y = rect.x + 16, rect.y + (rect.height - THUMB_H) // 2
        tw = 200
        if snap["thumb"]:
            data, size = snap["thumb"]
            tw = size[0]
            screen.blit(pygame.image.frombuffer(data, size, "RGB"), (x, y))
            pygame.draw.rect(screen, theme["soft"], (x - 1, y - 1, size[0] + 2, size[1] + 2), width=1)
        else:
            screen.blit(self._font(16).render("Starting camera...", True, theme["fg"]), (x, y))
        tx = x + tw + 28
        title = "Hand gestures" if self.mode == "hand" else "Body jump"
        screen.blit(self._font(18, True).render(f"{title}  ·  {self.backend.name} tracking", True, theme["fg"]), (tx, y))
        if self.worker.error:
            msg, color = f"Camera problem: {self.worker.error}  -  use Space to play", (214, 76, 76)
        else:
            msg, color = snap["message"], theme["fg"]
        screen.blit(self._font(16).render(msg, True, color), (tx, y + 30))

        bar_w, bar_h, by = 300, 12, y + 66
        pygame.draw.rect(screen, theme["track"], (tx, by, bar_w, bar_h), border_radius=6)
        if snap["state"] == "calibrating":
            fill, label = snap["progress"], "calibrating"
            pygame.draw.rect(screen, theme["accent"], (tx, by, max(2, int(bar_w * fill)), bar_h), border_radius=6)
        else:
            ratio = max(0.0, min(1.2, snap["rise"] / snap["threshold"]))
            label = "openness" if self.mode == "hand" else "jump height"
            col = theme["accent"] if ratio < 1 else (251, 140, 0)
            pygame.draw.rect(screen, col, (tx, by, max(2, int(bar_w * ratio / 1.2)), bar_h), border_radius=6)
            mark = tx + int(bar_w / 1.2)                      # where it counts
            pygame.draw.line(screen, theme["fg"], (mark, by - 3), (mark, by + bar_h + 3), 2)
        screen.blit(self._font(13).render(label, True, theme["soft"]), (tx + bar_w + 10, by - 2))

        info = f"Jumps detected: {snap['triggers']}     Camera {snap['fps']:.0f} fps, delay ~{snap['latency_ms']:.0f} ms"
        screen.blit(self._font(13).render(info, True, theme["soft"]), (tx, by + 26))

    def close(self):
        self.worker.stop()
        self.worker.join(timeout=1.0)
        try:
            self.worker.capture.release()
        except Exception:
            pass
        try:
            self.backend.close()
        except Exception:
            pass
"""
Finds the webcam settings that give the best frame rate.   Run:  python camera_test.py

It tries each combination for a few seconds, prints the fps it really gets, and at the end
tells you the exact command to start the game with.  Stand in front of the camera with the
room lit as you will play, and close Teams / Zoom / browser tabs that use the camera.
"""
import os
import sys
import time

import cv2

SECONDS = 2.5
IS_WIN = os.name == "nt"
APIS = [("dshow", cv2.CAP_DSHOW), ("msmf", cv2.CAP_MSMF)] if IS_WIN else [("any", cv2.CAP_ANY)]
FORMATS = [("MJPG", "MJPG"), ("default", None)]
SIZES = [(640, 480), (1280, 720)]
EXPOSURES = [None, -4, -5, -6, -7]


def measure(index, api, fourcc, size, exposure=None):
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened():
        return None
    try:
        if fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if exposure is not None:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
        for _ in range(5):                          # let the camera settle
            cap.read()
        n, bright, t0 = 0, 0.0, time.monotonic()
        while time.monotonic() - t0 < SECONDS:
            ok, frame = cap.read()
            if not ok:
                return 0.0, 0.0, size, False
            n += 1
            bright += float(frame.mean())
        fps = n / (time.monotonic() - t0)
        h, w = frame.shape[:2]
        gray = abs(float(frame[..., 0].mean()) - float(frame[..., 2].mean())) < 3   # IR cameras look grey
        return fps, bright / max(n, 1), (w, h), gray
    finally:
        cap.release()


def main():
    print(f"Testing each setting for {SECONDS:.1f} s - about a minute in total. Stay in front of the camera.\n")
    results = []
    for index in (0, 1):
        for api_name, api in APIS:
            for fmt_name, fourcc in FORMATS:
                for size in SIZES:
                    r = measure(index, api, fourcc, size)
                    label = f"camera {index} | {api_name:5} | {fmt_name:7} | asked {size[0]}x{size[1]}"
                    if r is None:
                        print(f"{label} -> can't open")
                        continue
                    fps, bright, got, gray = r
                    note = "  (grey picture = probably the IR camera)" if gray else ""
                    print(f"{label} -> {fps:5.1f} fps, got {got[0]}x{got[1]}, brightness {bright:3.0f}/255{note}")
                    results.append((fps, index, api_name, fmt_name, size, gray))
    if not results:
        sys.exit("\nNo camera could be opened. Close other apps that use it and try again.")

    colour = [r for r in results if not r[5]] or results
    best = max(colour, key=lambda r: (round(r[0]), r[4][0] == 640))      # prefer 640 wide when fps ties
    fps, index, api_name, fmt_name, size, _ = best
    print(f"\nBest so far: camera {index}, {api_name}, {fmt_name}, {size[0]}x{size[1]} -> {fps:.1f} fps")

    if fps < 26:
        print("\nStill under 30 fps - trying fixed (shorter) exposures, which stops the camera slowing down in dim light:")
        api = dict(APIS)[api_name]
        fourcc = dict(FORMATS)[fmt_name]
        best_exp = None
        for exp in EXPOSURES[1:]:
            r = measure(index, api, fourcc, size, exp)
            if r is None:
                continue
            print(f"  exposure {exp:3} -> {r[0]:5.1f} fps, brightness {r[1]:3.0f}/255")
            if r[0] > fps + 3 and r[1] > 40:                     # faster AND not black
                fps, best_exp = r[0], exp
        if best_exp is not None:
            print(f"\nExposure {best_exp} helps ({fps:.1f} fps).")
        best = (fps, index, api_name, fmt_name, size, False)
    else:
        best_exp = None

    cmd = f"python game.py --controller vision --camera {index}"
    if IS_WIN and api_name != "dshow":
        cmd += f" --camera-api {api_name}"
    if best_exp is not None:
        cmd += f" --exposure {best_exp}"
    print("\nStart the game with:\n  " + cmd)
    if fps < 26:
        print("\nStill slow? The cause is almost always dim light or a laptop camera effect (see the notes I sent).")


if __name__ == "__main__":
    main()
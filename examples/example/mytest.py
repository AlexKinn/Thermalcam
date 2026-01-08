#!/usr/bin/python3
# -*- coding:utf-8 -*-

import os, sys, time, math, logging

# --- Waveshare lib path setup (same pattern as your OLED test) ---
picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_OLED import OLED_1in5_rgb
from PIL import Image, ImageDraw, ImageFont

import board
import busio
import adafruit_mlx90640

logging.basicConfig(level=logging.INFO)

# ----------------- Thermal settings -----------------
MINTEMP = 20.0
MAXTEMP = 50.0

# MLX is 32x24
SRC_W, SRC_H = 32, 24

# OLED is typically 128x128 for this Waveshare model
DST_W, DST_H = 128, 128

# Preserve aspect ratio: 32x24 scaled by 4 -> 128x96
THERM_W, THERM_H = 128, 96
THERM_X, THERM_Y = 0, 0

UI_Y = THERM_H  # text area starts below thermal image (y=96)

# ----------------- Colormap setup -----------------
heatmap = (
    (0.0,  (0, 0, 0)),
    (0.20, (0, 0, 128)),
    (0.40, (0, 128, 0)),
    (0.60, (128, 0, 0)),
    (0.80, (192, 192, 0)),
    (0.90, (255, 192, 0)),
    (1.00, (255, 255, 255)),
)
COLORDEPTH = 1000

def constrain(val, min_val, max_val):
    return min(max_val, max(min_val, val))

def map_value(x, in_min, in_max, out_min, out_max):
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

def gaussian(x, a, b, c, d=0):
    return a * math.exp(-((x - b) ** 2) / (2 * c**2)) + d

def gradient(x, width, cmap, spread=1):
    width = float(width)
    r = sum(gaussian(x, p[1][0], p[0] * width, width / (spread * len(cmap))) for p in cmap)
    g = sum(gaussian(x, p[1][1], p[0] * width, width / (spread * len(cmap))) for p in cmap)
    b = sum(gaussian(x, p[1][2], p[0] * width, width / (spread * len(cmap))) for p in cmap)
    return (
        int(constrain(r, 0, 255)),
        int(constrain(g, 0, 255)),
        int(constrain(b, 0, 255)),
    )

colormap = [gradient(i, COLORDEPTH, heatmap) for i in range(COLORDEPTH)]

# ----------------- Init OLED -----------------
disp = OLED_1in5_rgb.OLED_1in5_rgb()
disp.Init()
disp.clear()

# Fonts (optional)
try:
    font = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 14)
except Exception:
    font = ImageFont.load_default()

# ----------------- Init MLX90640 -----------------
# Note: MLX on I2C; OLED may be SPI depending on your Waveshare board, which is fine.
i2c = busio.I2C(board.SCL, board.SDA)
mlx = adafruit_mlx90640.MLX90640(i2c)

# Set a realistic refresh rate. 32Hz is often optimistic depending on wiring/bus stability.
mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_4_HZ

frame = [0] * (SRC_W * SRC_H)

def frame_to_rgb_pixels(frame_vals):
    # Convert temps to RGB tuples (length 768)
    out = [None] * (SRC_W * SRC_H)
    for i, t in enumerate(frame_vals):
        idx = int(constrain(map_value(t, MINTEMP, MAXTEMP, 0, COLORDEPTH - 1), 0, COLORDEPTH - 1))
        out[i] = colormap[idx]
    return out

last = time.monotonic()
fps = 0.0

try:
    while True:
        t0 = time.monotonic()
        try:
            mlx.getFrame(frame)
        except ValueError:
            continue  # transient read errors are common; just retry

        # Compute FPS
        dt = t0 - last
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else (1.0 / dt)
        last = t0

        # Build 32x24 image
        pixels = frame_to_rgb_pixels(frame)
        img_small = Image.new("RGB", (SRC_W, SRC_H))
        img_small.putdata(pixels)

        # Scale to 128x96 using nearest-neighbor for speed (crisp pixel blocks)
        img_therm = img_small.resize((THERM_W, THERM_H), Image.NEAREST)

        # Compose full 128x128 frame
        canvas = Image.new("RGB", (DST_W, DST_H), "BLACK")
        canvas.paste(img_therm, (THERM_X, THERM_Y))

        # Overlay UI text in the bottom area
        draw = ImageDraw.Draw(canvas)
        tmin = min(frame)
        tmax = max(frame)
        tcenter = frame[(SRC_H // 2) * SRC_W + (SRC_W // 2)]
        draw.text((2, UI_Y + 2), f"min {tmin:0.1f}C  max {tmax:0.1f}C", font=font, fill="WHITE")
        draw.text((2, UI_Y + 18), f"ctr {tcenter:0.1f}C  {fps:0.1f} fps", font=font, fill="WHITE")

        # Push to OLED
        disp.ShowImage(disp.getbuffer(canvas))

        # Optional throttle (start conservative)
        time.sleep(0.02)

except KeyboardInterrupt:
    disp.clear()
    disp.module_exit()

"""Assemble the digital-twin demonstration video from the frames recorded by revit/batch/dt_video.py.

    .venv\\Scripts\\python experiments\\make_twin_video.py

Reads data/twin/video/frame_NN.png and steps.jsonl (real Revit renders and measured timings),
adds captions and a severity legend, and writes paper/supplementary/Video_1_digital_twin_demo.mp4
(1920 x 1080, H.264, 25 fps). Needs imageio-ffmpeg.
"""
from __future__ import annotations

import json
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "twin" / "video"
OUT = ROOT / "paper" / "supplementary" / "Video_1_digital_twin_demo.mp4"
W, H, FPS = 1920, 1080, 25
INK, MUTED, BG, BAR = (20, 20, 20), (95, 95, 95), (255, 255, 255), (244, 244, 241)
LEGEND = [("Critical", (220, 38, 38)), ("Major", (234, 88, 12)), ("Minor", (202, 138, 4)),
          ("Negligible", (100, 116, 139)), ("Clearance only", (37, 99, 235)), ("No clash", (73, 73, 55))]
REPO = "github.com/Darkiii-2514/DT-Clash-Detection-Paper"


def font(size, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), ("arialbd.ttf" if bold else "arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def card(title, lines, sub=None):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    y = 330
    d.text((W // 2, y), title, font=font(60, True), fill=INK, anchor="mm")
    y += 90
    for ln in lines:
        d.text((W // 2, y), ln, font=font(34), fill=INK, anchor="mm")
        y += 54
    if sub:
        d.text((W // 2, H - 90), sub, font=font(24), fill=MUTED, anchor="mm")
    return im


def scene(frame, step_title, caption, note=None):
    """Revit frame (white margins trimmed) with a title bar, legend and caption."""
    src = Image.open(frame).convert("RGB")
    bbox = Image.eval(src, lambda v: 255 - v).getbbox() or (0, 0, *src.size)
    pad = 30
    src = src.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                    min(src.width, bbox[2] + pad), min(src.height, bbox[3] + pad)))
    im = Image.new("RGB", (W, H), BG)
    top, bottom, right = 92, 168, 300
    box_w, box_h = W - right - 40, H - top - bottom
    s = min(box_w / src.width, box_h / src.height)
    shown = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
    im.paste(shown, (40 + (box_w - shown.width) // 2, top + (box_h - shown.height) // 2))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, top - 12), fill=BAR)
    d.text((40, (top - 12) // 2), step_title, font=font(38, True), fill=INK, anchor="lm")
    d.text((W - 40, (top - 12) // 2), "Revit 2027 · Snowdon Towers sample", font=font(24), fill=MUTED, anchor="rm")
    lx, ly = W - right + 10, top + 30
    d.text((lx, ly), "Proposed severity", font=font(26, True), fill=INK)
    ly += 50
    for name, col in LEGEND:
        d.rectangle((lx, ly, lx + 34, ly + 26), fill=col)
        d.text((lx + 48, ly + 13), name, font=font(24), fill=INK, anchor="lm")
        ly += 44
    d.rectangle((0, H - bottom + 12, W, H), fill=BAR)
    d.text((40, H - bottom + 52), caption, font=font(32), fill=INK, anchor="lm")
    if note:
        d.text((40, H - bottom + 108), note, font=font(24), fill=MUTED, anchor="lm")
    return im


def fade(a, b, seconds):
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    n = max(1, int(seconds * FPS))
    return [Image.fromarray((a + (b - a) * (i + 1) / n).astype(np.uint8)) for i in range(n)]


def main():
    steps = [json.loads(line) for line in (SRC / "steps.jsonl").read_text().splitlines()]
    if any("fatal" in s for s in steps):
        raise SystemExit("the Revit run failed; see data/twin/video/steps.jsonl")
    s0, s1, s2 = steps[:3]
    hard = ", ".join(s1["beam_hard"])
    clips = [
        (card("Digital twin: load path-aware clash severity",
              ["A design change in Revit, re-analysed and written back automatically"],
              "Real run on one workstation. Frames are exported from Revit after each step; times are measured."), 4.0),
        (scene(SRC / "frame_00.png", "1  Current design",
               f"Steel beam {s0['beam'].split(' : ')[-1]} (level {s0['level']}) runs just above a duct: clearance clash only (blue).",
               f"{s0['n_clashes']:,} clashes in the federated model."), 4.5),
        (scene(SRC / "frame_00.png", "2  Change in Revit",
               f"The beam is {s1['label'].replace('beam ', '')} in one Revit transaction.",
               "The change hook sends the changed elements to the twin service."), 2.5),
        (scene(SRC / "frame_01.png", "3  Results written back",
               f"New hard clashes on the beam: {hard}. The beam turns Critical.",
               f"{s1['change_to_results_ms'] / 1000:.1f} s from edit to results (twin service {s1['service_ms'] / 1000:.1f} s). "
               f"Joists resting on the beam moved too: {s0['n_clashes']:,} → {s1['n_clashes']:,} clashes."), 6.0),
        (scene(SRC / "frame_01.png", "4  Change in Revit", "The beam is restored to its original height.",
               "Same loop: change hook, incremental update, write-back."), 2.5),
        (scene(SRC / "frame_02.png", "5  Results written back",
               "The new clashes are resolved and the beam is back to a clearance clash only.",
               f"{s2['change_to_results_ms'] / 1000:.1f} s from edit to results (twin service {s2['service_ms'] / 1000:.1f} s). "
               f"{s2['n_clashes']:,} clashes, as before."), 4.5),
        (card("Code, data and scripts", [REPO],
              "Video assembled from Revit image exports with experiments/make_twin_video.py."), 3.5),
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio_ffmpeg.write_frames(str(OUT), (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                         quality=8, macro_block_size=8)
    writer.send(None)
    prev = None
    n = 0
    for im, secs in clips:
        if prev is not None:
            for f in fade(prev, im, 0.5):
                writer.send(np.asarray(f).tobytes())
                n += 1
        for _ in range(int(secs * FPS)):
            writer.send(np.asarray(im).tobytes())
            n += 1
        prev = im
    writer.close()
    for i, (im, _) in enumerate(clips):
        im.save(SRC / f"scene_{i}.png")
    print(f"-> {OUT} ({n / FPS:.1f} s, {OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

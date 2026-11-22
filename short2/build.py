"""Assemble @Bizstring "5 Secrets Employers Use" into a finished 1080x1920 MP4."""
import subprocess, sys

FPS = 30
W, H = 1080, 1920
BASE_H = 1935  # 768x1376 scaled to 1080 wide
TOTAL = 59.9

# name, source, kind, start, end, zoom_from, zoom_to, focus_x, focus_y
SEGMENTS = [
    ("H",  "h.png",     "still",  0.00,  7.30, 1.00, 1.12, 0.50, 0.55),
    ("5a", "s5.png",    "still",  7.30, 13.30, 1.00, 1.08, 0.50, 0.40),
    ("5b", "s5.png",    "still", 13.30, 20.75, 1.30, 1.45, 0.80, 0.12),
    ("4a", "s4.png",    "still", 20.75, 25.90, 1.00, 1.08, 0.55, 0.35),
    ("4b", "s4.png",    "still", 25.90, 29.50, 1.35, 1.48, 0.55, 0.22),
    ("3",  "clip3.mp4", "clip",  29.50, 36.60, 1.00, 1.06, 0.50, 0.45),
    ("2",  "clip2.mp4", "clip",  36.60, 44.50, 1.00, 1.08, 0.55, 0.35),
    ("1",  "clip1.mp4", "clip",  44.50, 52.85, 1.00, 1.10, 0.50, 0.40),
    ("E",  "end.png",   "still", 52.85, TOTAL, 1.00, 1.06, 0.50, 0.60),
]


def run(cmd):
    subprocess.run(cmd, check=True)


def push_chain(dur, z0, z1, fx, fy):
    z = f"({z0}+({z1}-{z0})*(1-cos(PI*min(t/{dur},1)))/2)"
    return (f"scale=w='trunc({W}*{z}/2)*2':h='trunc({BASE_H}*{z}/2)*2':eval=frame:flags=lanczos,"
            f"crop={W}:{H}:x='(iw-{W})*{fx}':y='(ih-{H})*{fy}'")


def build(name, src, kind, start, end, z0, z1, fx, fy):
    dur = round(end - start, 3)
    out = f"seg_{name}.mp4"
    if kind == "still":
        inp = ["-loop", "1", "-framerate", str(FPS), "-i", src]
        pre = f"scale={W}:{BASE_H}:flags=lanczos,"
    else:
        src_dur = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]).decode())
        factor = min(dur / src_dur, 1.4)
        inp = ["-i", src]
        pre = (f"setpts={factor:.4f}*PTS,fps={FPS},scale={W}:{BASE_H}:flags=lanczos,"
               f"tpad=stop_mode=clone:stop_duration=5,")
    vf = pre + push_chain(dur, z0, z1, fx, fy) + f",trim=duration={dur},setpts=PTS-STARTPTS,format=yuv420p"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inp, "-vf", vf, "-t", str(dur),
         "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-an", out])
    return out


def main():
    only = sys.argv[1:]
    segs = [build(*s) for s in SEGMENTS if not only or s[0] in only]
    if only:
        return
    with open("concat.txt", "w") as f:
        f.writelines(f"file '{s}'\n" for s in segs)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "concat.txt",
         "-filter_complex", "[0:v]ass=captions.ass[v]",
         "-map", "[v]", "-an", "-t", str(TOTAL),
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart",
         "video_only_v4.mp4"])


if __name__ == "__main__":
    main()

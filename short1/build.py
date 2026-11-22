"""Assemble @Bizstring Short #1 into a 1080x1920 MP4."""
import subprocess, os, sys

FPS = 30
PANEL_W, PANEL_H, PANEL_Y = 1080, 1350, 250
BG = "0xF2E4CC"

# (name, source, kind, start, end, crop w:h:x:y, extra)
SEGMENTS = [
    ("A", "clip1.mp4", "clip",  0.00,  6.62, (518, 648, 535, 0), {}),
    ("B", "s2.png",    "still", 6.62, 10.50, (504, 630, 600, 0), {}),
    ("C", "s3.png",    "still", 10.50, 13.70, (488, 610, 445, 0), {}),
    ("D", "clip2.mp4", "pan",  13.70, 20.92, (536, 670, 0, 0), {}),
    ("E", "s5.png",    "still", 20.92, 24.75, (614, 768, 300, 0), {}),
    ("F", "s1.png",    "still", 24.75, 28.80, (518, 648, 535, 0), {}),
]


def run(cmd):
    print(" ".join(cmd)[:300])
    subprocess.run(cmd, check=True)


def frame_filter(panel_chain, dur):
    """Place a 1080x1350 panel on the cream background with a soft shadow."""
    return (
        f"color=c={BG}:s=1080x1920:r={FPS}:d={dur},noise=alls=5:allf=u,format=yuv420p[bg];"
        f"{panel_chain}[p];"
        f"[bg]drawbox=x=18:y={PANEL_Y + 14}:w={PANEL_W - 24}:h={PANEL_H}:color=black@0.18:t=fill[bgs];"
        f"[bgs][p]overlay=x=0:y={PANEL_Y}:shortest=1,format=yuv420p"
    )


def build_segment(name, src, kind, start, end, crop, extra):
    dur = round(end - start, 3)
    w, h, x, y = crop
    n = int(round(dur * FPS))
    out = f"seg_{name}.mp4"
    if kind == "still":
        chain = (
            f"[0:v]crop={w}:{h}:{x}:{y},scale=2160:2700:flags=lanczos,"
            f"zoompan=z='1+0.07*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={PANEL_W}x{PANEL_H}:fps={FPS},"
            f"trim=duration={dur},setpts=PTS-STARTPTS"
        )
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", src]
    else:
        src_dur = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]).decode())
        factor = dur / src_dur
        if kind == "pan":
            # hold on the meeting table, glide to the boss's door, glide to the empty hallway
            xexpr = ("'if(lt(t,2.0),0,if(lt(t,3.3),460*(t-2.0)/1.3,if(lt(t,4.1),460,"
                     "if(lt(t,5.6),460+380*(t-4.1)/1.5,840))))'")
        else:
            xexpr = str(x)
        chain = (
            f"[0:v]scale=1376:768:flags=lanczos,setpts={factor:.4f}*PTS,fps={FPS},"
            f"crop={w}:{h}:{xexpr}:{y},scale={PANEL_W}:{PANEL_H}:flags=lanczos,"
            f"tpad=stop_mode=clone:stop_duration=2,trim=duration={dur},setpts=PTS-STARTPTS"
        )
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    cmd += ["-filter_complex", frame_filter(chain, dur), "-t", str(dur), "-r", str(FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-an", out]
    run(cmd)
    return out


def main():
    only = sys.argv[1:]
    segs = []
    for s in SEGMENTS:
        if only and s[0] not in only:
            continue
        segs.append(build_segment(*s))
    if only:
        return
    with open("concat.txt", "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "concat.txt",
         "-i", "voice.mp3",
         "-filter_complex", "[0:v]ass=captions.ass[v]",
         "-map", "[v]", "-map", "1:a", "-t", "28.8",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "256k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart",
         "Bizstring_Short1_No_Right_Answers.mp4"])


if __name__ == "__main__":
    main()

"""
Safe montage builder using ffmpeg.
Only use clips you own, AI-generated clips, royalty-free stock, or properly attributed Creative Commons clips
paired with an original voiceover track so your channel remains eligible for YouTube monetization.
"""
import subprocess
from pathlib import Path


def build_montage(
    clips_dir: str,
    voiceover_path: str,
    output_path: str,
    vertical_shorts: bool = False,
) -> str:
    clips = sorted(
        [p for p in Path(clips_dir).iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv"}]
    )
    if not clips:
        raise ValueError(f"No video clips found in {clips_dir}")
    if not Path(voiceover_path).exists():
        raise FileNotFoundError(f"Voiceover not found: {voiceover_path}")

    concat_list = Path(clips_dir) / "_concat.txt"
    lines = [f"file '{c.resolve()}'" for c in clips]
    concat_list.write_text("\n".join(lines), encoding="utf-8")

    scale_filter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        if vertical_shorts
        else "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-i",
        voiceover_path,
        "-vf",
        scale_filter,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-c:a",
        "aac",
        "-shortest",
        output_path,
    ]
    subprocess.run(cmd, check=True)
    concat_list.unlink(missing_ok=True)
    return output_path

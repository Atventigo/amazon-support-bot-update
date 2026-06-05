"""
play_chime.py — Audio notification system for Claude agent responses.

Usage:
    python execution/play_chime.py                  # completion chime (default)
    python execution/play_chime.py completion       # pleasant finish chime
    python execution/play_chime.py approval         # waiting for approval tone

Decorator usage:
    from execution.play_chime import with_completion_chime

    @with_completion_chime
    def my_task():
        ...
"""

import sys
import io
import math
import struct
import wave
import threading
import functools

# ─────────────────────────────────────────────
# Platform detection
# ─────────────────────────────────────────────
import platform
PLATFORM = platform.system()  # "Windows", "Darwin", "Linux"

VOLUME = 0.3  # 0.0 – 1.0


# ─────────────────────────────────────────────
# Windows WAV tone generation at controlled volume
# ─────────────────────────────────────────────
def _make_tone_wav(freq: int, duration_ms: int, volume: float = VOLUME) -> bytes:
    """Generate a single tone WAV with fade-in/out and a trailing flush buffer."""
    sample_rate = 44100
    n_samples = int(sample_rate * duration_ms / 1000)
    peak = int(32767 * volume)
    frames = bytearray()
    for i in range(n_samples):
        fade_in = min(1.0, i / (sample_rate * 0.01))
        fade_out = min(1.0, (n_samples - i) / (sample_rate * 0.02))
        sample = int(peak * fade_in * fade_out * math.sin(2 * math.pi * freq * i / sample_rate))
        frames += struct.pack("<h", sample)
    # Trailing silence ensures the Windows audio buffer fully flushes before PlaySound returns
    frames += b"\x00\x00" * int(sample_rate * 0.07)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def _win_beep(freq: int, duration_ms: int):
    import winsound
    winsound.PlaySound(_make_tone_wav(freq, duration_ms), winsound.SND_MEMORY)


def _play_completion_windows():
    """Pleasant 3-note ascending chime — each note distinct and separated."""
    import random
    roots = [523, 587, 659, 698, 784]  # C5, D5, E5, F5, G5
    root = random.choice(roots)
    semitone = 2 ** (1 / 12)
    freqs = [int(root * (semitone ** i)) for i in [0, 4, 7]]
    for freq in freqs:
        _win_beep(freq, 140)


def _play_approval_windows():
    """Two-note rising alert — each note distinct and separated."""
    import random
    pairs = [(440, 660), (392, 587), (349, 523), (330, 494)]
    low, high = random.choice(pairs)
    _win_beep(low, 150)
    _win_beep(high, 200)


# ─────────────────────────────────────────────
# macOS tone generation (afplay system sounds)
# ─────────────────────────────────────────────
def _play_completion_mac():
    import subprocess, random
    sounds = [
        "/System/Library/Sounds/Glass.aiff",
        "/System/Library/Sounds/Ping.aiff",
        "/System/Library/Sounds/Pop.aiff",
        "/System/Library/Sounds/Tink.aiff",
    ]
    subprocess.run(["afplay", "-v", str(VOLUME), random.choice(sounds)], capture_output=True)


def _play_approval_mac():
    import subprocess, random
    sounds = [
        "/System/Library/Sounds/Funk.aiff",
        "/System/Library/Sounds/Sosumi.aiff",
        "/System/Library/Sounds/Basso.aiff",
    ]
    subprocess.run(["afplay", "-v", str(VOLUME), random.choice(sounds)], capture_output=True)


# ─────────────────────────────────────────────
# Linux tone generation (paplay / aplay / beep)
# ─────────────────────────────────────────────
def _play_completion_linux():
    import subprocess, random
    sounds = [
        "/usr/share/sounds/freedesktop/stereo/complete.oga",
        "/usr/share/sounds/freedesktop/stereo/bell.oga",
        "/usr/share/sounds/freedesktop/stereo/message.oga",
    ]
    sound = random.choice(sounds)
    for player in [["paplay", sound], ["aplay", sound]]:
        try:
            result = subprocess.run(player, capture_output=True)
            if result.returncode == 0:
                return
        except FileNotFoundError:
            continue
    # Fallback: terminal bell
    print("\a", end="", flush=True)


def _play_approval_linux():
    import subprocess, random
    sounds = [
        "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga",
        "/usr/share/sounds/freedesktop/stereo/dialog-error.oga",
    ]
    sound = random.choice(sounds)
    for player in [["paplay", sound], ["aplay", sound]]:
        try:
            result = subprocess.run(player, capture_output=True)
            if result.returncode == 0:
                return
        except FileNotFoundError:
            continue
    print("\a\a", end="", flush=True)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────
def play(sound_type: str = "completion"):
    """
    Play a chime non-blocking.

    sound_type:
        "completion" — pleasant finish chime (different tone each time)
        "approval"   — alert tone for pending approval
    """
    def _play():
        try:
            if sound_type == "approval":
                if PLATFORM == "Windows":
                    _play_approval_windows()
                elif PLATFORM == "Darwin":
                    _play_approval_mac()
                else:
                    _play_approval_linux()
            else:
                if PLATFORM == "Windows":
                    _play_completion_windows()
                elif PLATFORM == "Darwin":
                    _play_completion_mac()
                else:
                    _play_completion_linux()
        except Exception:
            pass  # Never crash the caller

    t = threading.Thread(target=_play, daemon=True)
    t.start()
    t.join(timeout=3)  # Wait up to 3s, then move on


def approval_reminder(interval_seconds: int = 5):
    """
    Start a background thread that plays the approval tone every
    `interval_seconds` until cancelled. Returns a cancel function.

        cancel = approval_reminder(5)
        # ... user approves ...
        cancel()
    """
    stop_event = threading.Event()

    def _loop():
        while not stop_event.wait(timeout=interval_seconds):
            play("approval")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

    def cancel():
        stop_event.set()

    return cancel


# ─────────────────────────────────────────────
# Decorator
# ─────────────────────────────────────────────
def with_completion_chime(func):
    """Decorator: plays a completion chime when the wrapped function returns."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            play("completion")
            return result
        except Exception:
            play("approval")  # Error = alert tone
            raise
    return wrapper


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    sound = sys.argv[1] if len(sys.argv) > 1 else "completion"
    if sound not in ("completion", "approval"):
        print(f"Unknown sound type '{sound}'. Use: completion | approval")
        sys.exit(1)
    play(sound)

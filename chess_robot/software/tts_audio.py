"""
Chess Robotic Tutor and Training System
Text-to-speech pipeline.

Synthesizes a phrase offline with pyttsx3 (no internet dependency - the
robot should be able to talk with no network at all), then converts it
to raw 16kHz mono 16-bit PCM, which is exactly the format the ESP32
firmware's I2S driver expects so it can be streamed straight to the
MAX98357A amplifier with no on-device decoding.

Requires: pyttsx3, pydub  (pydub additionally requires the `ffmpeg`
system binary to be installed and on PATH).
"""

import os
import tempfile

import pyttsx3
import numpy as np
import sounddevice as sd
from pydub import AudioSegment


def synthesize_to_pcm(text: str, sample_rate: int = 16000, speech_rate: int = 160) -> bytes:
    """Returns raw little-endian 16-bit mono PCM bytes at sample_rate Hz."""
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    engine.setProperty('voice', voices[1].id)
    engine.setProperty('rate', speech_rate)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        engine.save_to_file(text, wav_path)
        engine.runAndWait()

        audio = AudioSegment.from_wav(wav_path)
        audio = audio.set_frame_rate(sample_rate).set_channels(1).set_sample_width(2)
        audio = audio + 10
        return audio.raw_data
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def chunk_pcm(pcm_bytes: bytes, max_chunk: int):
    """Yields successive slices of pcm_bytes no larger than max_chunk -
    use this if you want manual control over streaming instead of relying
    on RobotInterface.speak_pcm()'s built-in chunking."""
    for i in range(0, len(pcm_bytes), max_chunk):
        yield pcm_bytes[i:i + max_chunk]

def play_local_mp3(file_path: str):
    """Loads an MP3 file and plays it through the current default system
    audio output device (e.g. a paired Bluetooth speaker). Blocks until
    playback finishes."""
    audio = AudioSegment.from_mp3(file_path)
    samples = np.array(audio.get_array_of_samples())
    if audio.channels == 2:
        samples = samples.reshape((-1, 2))
    sd.play(samples, samplerate=audio.frame_rate)
    sd.wait()
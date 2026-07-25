import os
import sys
import json
import wave
import threading
import struct
import math
import time
import pyaudio
from vosk import Model, KaldiRecognizer
import requests
import pygame

# Tumhare floating dot se connect karne ke liye
from core.floating_ui import set_dot_state

class WakeWordEngine:
    def __init__(self):
        self.is_listening = False
        self.RECORD_SECONDS = 5
        self.OUTPUT_FILENAME = "temp_command.wav"
        
        # Model path
        self.model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")
        self.model = None
        self.recognizer = None
        self.pa = None
        self.stream = None
        
        # Ek baar Pygame shuru kar lo taaki crash na ho
        if not pygame.mixer.get_init():
            pygame.mixer.init()

    def _get_rms(self, data):
        """Python 3.13 Safe: Audio ki volume (loudness) calculate karta hai"""
        count = len(data) // 2
        if count == 0: return 0
        shorts = struct.unpack(f"{count}h", data)
        sum_squares = sum(s * s for s in shorts)
        return math.sqrt(sum_squares / count)

    def start_listening(self):
        """Background daemon thread mein engine start karta hai"""
        if not os.path.exists(self.model_path):
            print(f"❌ Vosk model not found at {self.model_path}. Please download and extract it.")
            return

        try:
            self.model = Model(self.model_path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.pa = pyaudio.PyAudio()
            self.stream = self.pa.open(
                format=pyaudio.paInt16, channels=1, rate=16000,
                input=True, frames_per_buffer=4000
            )
            self.stream.start_stream()
            self.is_listening = True
            set_dot_state("idle")
            print("👂 [Wake-Word] Offline Engine Started. Say 'Lisa' to wake me up.")
            self._listen_loop()
        except Exception as e:
            print(f"Wake word initialization failed: {e}")

    def _listen_loop(self):
        while self.is_listening:
            try:
                data = self.stream.read(4000, exception_on_overflow=False)
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").lower()
                    
                    if "lisa" in text:
                        print("\n🎯 Wake Word 'Lisa' Detected!")
                        set_dot_state("listening")
                        self._record_command()
                        
                        # Command execute karo (iske andar ab continuous loop hai)
                        self._execute_command()
            except Exception as e:
                pass

    def _record_command(self):
        """Dynamic recording: Jab tak user bol raha hai record karega, 1.5 sec silence par stop hoga."""
        print("🎙️ Recording command... (Speak as long as you want)")
        frames = []
        silence_threshold = 500  # Loudness threshold
        silence_duration = 1.5   # 1.5 second tak kuch na bolne par band hoga
        max_duration = 30        # Maximum 30 seconds tak record karega taaki atke na
        
        start_time = time.time()
        last_spoken_time = time.time()
        
        # Purana audio buffer clear kar lo taaki purani aawaz mix na ho
        while self.stream.get_read_available() > 0:
            self.stream.read(self.stream.get_read_available(), exception_on_overflow=False)

        while True:
            data = self.stream.read(1024, exception_on_overflow=False)
            frames.append(data)
            
            # _get_rms use karke volume check karo
            rms = self._get_rms(data)
            current_time = time.time()
            
            if rms > silence_threshold:
                last_spoken_time = current_time  # Jab tak awaaz aa rahi hai, silence timer reset karo
            
            # Agar 1.5 seconds tak shanti hai (aur kam se kam 2 second record ho chuka hai)
            if current_time - last_spoken_time > silence_duration:
                if current_time - start_time > 2.0:
                    print("✅ Silence detected. Stopping recording.")
                    break
                    
            # Hard limit (30 seconds)
            if current_time - start_time > max_duration:
                print("⏳ Max recording time reached (30s).")
                break

        with wave.open(self.OUTPUT_FILENAME, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.pa.get_sample_size(pyaudio.paInt16))
            wf.setframerate(16000)
            wf.writeframes(b''.join(frames))
        print("✅ Command saved.")

    def _wait_for_follow_up(self, timeout=7):
        """7 seconds tak bina 'Lisa' bole tumhare bolne ka wait karta hai"""
        print(f"👂 Waiting {timeout} seconds for follow-up command...")
        set_dot_state("listening")
        start_time = time.time()
        
        # Purana audio buffer clear kar lo
        while self.stream.get_read_available() > 0:
            self.stream.read(self.stream.get_read_available(), exception_on_overflow=False)

        # Jab tak 7 second poore na ho jaye, volume check karo
        while time.time() - start_time < timeout:
            data = self.stream.read(1024, exception_on_overflow=False)
            rms = self._get_rms(data)
            
            # Agar volume 500 (threshold) se zyada hai, matlab tumne bolna shuru kar diya!
            if rms > 500:
                print("\n🗣️ Speech detected! Recording follow-up...")
                return True
                
        return False

    def _execute_command(self):
        # ── CONTINUOUS CONVERSATION LOOP ──
        while True:
            set_dot_state("processing")
            print("⚙️ Sending command to Lisa's Brain...")
            
            try:
                with open(self.OUTPUT_FILENAME, 'rb') as f:
                    files = {'audio': (self.OUTPUT_FILENAME, f, 'audio/wav')}
                    res = requests.post("http://127.0.0.1:8765/api/voice", files=files)
                    
                if res.status_code == 200:
                    data = res.json()
                    print(f"🗣️ You said: {data.get('transcript')}")
                    print(f"🤖 Lisa replied: {data.get('reply')}")
                    
                    tts_text = data.get("tts_text")
                    if tts_text:
                        tts_res = requests.post("http://127.0.0.1:8765/api/tts", json={"text": tts_text})
                        if tts_res.status_code == 200:
                            content_type = tts_res.headers.get("Content-Type", "")
                            ext = ".wav" if "wav" in content_type else ".mp3"
                            reply_audio_path = f"temp_reply{ext}"
                            
                            with open(reply_audio_path, "wb") as out:
                                out.write(tts_res.content)
                                
                            set_dot_state("speaking")
                            pygame.mixer.music.load(reply_audio_path)
                            pygame.mixer.music.play()
                            
                            while pygame.mixer.music.get_busy():
                                pygame.time.Clock().tick(10)
                                
                            # Audio file ko release karo taaki agli baar overwrite ho sake
                            pygame.mixer.music.unload()
                            
                # ── 7 SECOND WAIT ──
                # Audio khatam hote hi, 7 second ka timer shuru hoga
                if self._wait_for_follow_up(timeout=7):
                    # Agar tumne kuch bola, toh wapas 5 sec record karo aur loop ghumao
                    self._record_command()
                    continue 
                else:
                    # Agar 7 sec tak kuch nahi bola, toh Lisa wapas so jayegi
                    print("😴 No follow-up detected. Going back to sleep.")
                    break
                    
            except Exception as e:
                print(f"❌ Error communicating with Lisa API: {e}")
                break
                
        # Loop break hone ke baad wapas Idle (Green)
        set_dot_state("idle")
        self.recognizer.Reset()

# Global instance
engine = WakeWordEngine()

def run_wake_word_background():
    t = threading.Thread(target=engine.start_listening, daemon=True)
    t.start()
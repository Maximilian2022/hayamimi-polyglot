import sounddevice as sd
import numpy as np

print("Default input device:", sd.default.device[0])
print("\n--- Audio Host APIs ---")
for i, h in enumerate(sd.query_hostapis()):
    print(f"API {i}: {h['name']} | keys: {list(h.keys())}")

print("\n--- Input Devices ---")
for i, d in enumerate(sd.query_devices()):
    if d['max_input_channels'] > 0:
        api_name = sd.query_hostapis(d['hostapi'])['name']
        print(f"[{i:2d}] {d['name']} | HostAPI: {api_name} | Max In: {d['max_input_channels']} | Def Rate: {d['default_samplerate']}")

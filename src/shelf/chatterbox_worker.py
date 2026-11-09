"""The DJ's natural voice: a long-running helper that speaks lines with Chatterbox, an open
voice model that sounds close to a real person, on the graphics card.

It runs in its own Python environment, keeps the model loaded, and takes one request per line
on stdin:
    {"text": "...", "ref": "/path/voice.wav" or null, "exaggeration": 0.6, "cfg": 0.4, "out": "/path/line.wav"}
`ref` is a short recording whose voice it takes on (null: Chatterbox's own voice). Each answer
is one line of JSON: {"ok": true, "seconds": 4.2} or {"ok": false, "error": "..."}.
The first line says where it runs: {"ready": true, "device": "cuda"}.

Standalone on purpose: it doesn't import Shelf. Usage:
    <chatterbox venv>/bin/python chatterbox_worker.py
"""

import json
import sys


def main() -> None:
    import torch
    import torchaudio as ta
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxTTS.from_pretrained(device=device)
    print(json.dumps({"ready": True, "device": device}), flush=True)
    for line in sys.stdin:
        try:
            req = json.loads(line)
            wav = model.generate(req["text"], audio_prompt_path=req.get("ref") or None,
                                 exaggeration=float(req.get("exaggeration", 0.6)), cfg_weight=float(req.get("cfg", 0.4)))
            ta.save(req["out"], wav.cpu(), model.sr)
            print(json.dumps({"ok": True, "seconds": round(wav.shape[-1] / model.sr, 2)}), flush=True)
        except Exception as e:  # report and carry on with the next line
            print(json.dumps({"ok": False, "error": str(e)[:300]}), flush=True)


if __name__ == "__main__":
    main()

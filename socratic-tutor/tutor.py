#!/usr/bin/env python3
"""Run the Socratic tutor in a terminal using a local Ollama model."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:11434"


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=600)


def ready():
    try:
        with urllib.request.urlopen(BASE + "/api/tags", timeout=2) as response:
            json.load(response)
        return True
    except (OSError, ValueError):
        return False


def setup(model):
    binary = ROOT / ".local" / "ollama" / "ollama"
    executable = str(binary) if binary.exists() else shutil.which("ollama")
    if not ready():
        if not executable:
            raise RuntimeError("Ollama is missing. Install it from https://ollama.com/download, then run ./tutor again.")
        directory = ROOT / ".local"
        directory.mkdir(exist_ok=True)
        env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434",
                   OLLAMA_MODELS=str(directory / "models"), OLLAMA_NO_CLOUD="1")
        with (directory / "ollama.log").open("a") as log:
            process = subprocess.Popen([executable, "serve"], env=env,
                                       stdout=log, stderr=log, start_new_session=True)
        print("Starting local Ollama…", flush=True)
        for _ in range(60):
            if ready():
                break
            if process.poll() is not None:
                raise RuntimeError("Ollama stopped. Check .local/ollama.log.")
            time.sleep(0.5)
        else:
            raise RuntimeError("Ollama did not start. Check .local/ollama.log.")
    with request("/api/tags") as response:
        models = json.load(response).get("models", [])
    if model not in {m["name"] for m in models}:
        print(f"Downloading {model} (first run only)…", flush=True)
        previous = None
        with request("/api/pull", {"model": model, "stream": True}) as response:
            for line in response:
                event = json.loads(line)
                if "error" in event:
                    raise RuntimeError(event["error"])
                total = event.get("total", 0)
                progress = f" {100 * event.get('completed', 0) / total:.0f}%" if total else ""
                status = event.get("status", "") + progress
                if status != previous:
                    print("\r" + status + " " * 15, end="", flush=True)
                    previous = status
        print()


def reply(model, messages):
    answer = []
    print("\nTutor: ", end="", flush=True)
    with request("/api/chat", {"model": model, "messages": messages,
                              "stream": True, "options": {"num_ctx": 16384}}) as response:
        for line in response:
            event = json.loads(line)
            if "error" in event:
                raise RuntimeError(event["error"])
            content = event.get("message", {}).get("content", "")
            answer.append(content)
            print(content, end="", flush=True)
    print("\n")
    result = "".join(answer)
    if not result.strip():
        raise RuntimeError("The model returned an empty answer. Please try again.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", nargs="*", help="Topic to study (or enter it when prompted)")
    parser.add_argument("--model", default="qwen2.5:3b", help="Local Ollama model (default: qwen2.5:3b)")
    args = parser.parse_args()
    if "cloud" in args.model.lower() or "/" in args.model:
        parser.error("Choose a local model name, such as qwen2.5:3b.")
    setup(args.model)
    print(f"\nSocratic Tutor · local model: {args.model}\nType /quit to exit. Ctrl+C also exits.\n")
    topic = " ".join(args.topic) or input("What would you like to learn? ").strip()
    if not topic or topic == "/quit":
        return
    skill = Path(__file__).with_name("SKILL.md").read_text()
    if skill.startswith("---"):
        skill = skill.split("---", 2)[2].strip()
    messages = [{"role": "system", "content": skill},
                {"role": "user", "content": f"Teach me {topic}. Start the diagnostic with one question."}]
    while True:
        answer = reply(args.model, messages)
        messages.append({"role": "assistant", "content": answer})
        text = input("You: ").strip()
        while not text:
            text = input("You: ").strip()
        if text.lower() in {"/quit", "/exit"}:
            return
        messages.append({"role": "user", "content": text})


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nSession ended.")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"\nError: {error}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Minimal PowerPrint/FlashForge network control helper for PowerSpec Ultra.

The printer listens on TCP 8899 and expects commands prefixed with "~".
Known-good command flow was recovered from the local PowerPrint binary.
"""

from __future__ import annotations

import argparse
import binascii
import re
import socket
import struct
import sys
import time
from pathlib import Path


DEFAULT_PORT = 8899
UPLOAD_BLOCK_SIZE = 4096
UPLOAD_MAGIC = b"\x5a\x5a\xa5\xa5"


class Printer:
    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.25)

    def close(self) -> None:
        self.sock.close()

    def read_for(self, seconds: float) -> str:
        end = time.time() + seconds
        chunks: list[bytes] = []
        while time.time() < end:
            try:
                data = self.sock.recv(8192)
                if data:
                    chunks.append(data)
                    end = max(end, time.time() + 0.15)
                else:
                    break
            except socket.timeout:
                continue
        return b"".join(chunks).decode("utf-8", "replace")

    def read_until(self, needles: tuple[str, ...], timeout: float = 10.0) -> str:
        end = time.time() + timeout
        text = ""
        while time.time() < end:
            try:
                self.sock.settimeout(min(0.2, max(0.01, end - time.time())))
                data = self.sock.recv(8192)
                if not data:
                    break
                text += data.decode("utf-8", "replace")
            except socket.timeout:
                continue
            if any(needle in text for needle in needles):
                return text
        raise TimeoutError(f"timed out waiting for {needles!r}; got {text!r}")

    def read_packet_ack(self, packet_id: int, timeout: float = 8.0) -> str:
        text = self.read_until(("ok", "Error", "error"), timeout=timeout)
        match = re.search(r"\bN(\d+)\s+ok\b", text)
        if match and int(match.group(1)) == packet_id:
            return text
        raise RuntimeError(f"unexpected ack for upload packet {packet_id}:\n{text}")

    def command(self, command: str, timeout: float = 5.0) -> str:
        if not command.startswith("~"):
            command = "~" + command
        self.sock.sendall(command.encode("ascii") + b"\r\n")
        return self.read_until(("ok", "failed", "Failed", "Error"), timeout=timeout)

    def acquire(self) -> str:
        return self.command("M601 S1")

    def release(self) -> str:
        return self.command("M602")

    def status(self) -> str:
        return self.command("M115") + self.command("M105") + self.command("M27")

    def upload(self, local_path: Path, remote_name: str) -> str:
        data = local_path.read_bytes()
        response = self.command(f"M28 {len(data)} {remote_name}", timeout=8.0)
        if "Writing to file:" not in response:
            raise RuntimeError(f"printer did not enter upload mode:\n{response}")

        total_packets = (len(data) + UPLOAD_BLOCK_SIZE - 1) // UPLOAD_BLOCK_SIZE
        progress_every = max(1, total_packets // 20)
        for packet_id, offset in enumerate(range(0, len(data), UPLOAD_BLOCK_SIZE)):
            chunk = data[offset : offset + UPLOAD_BLOCK_SIZE]
            padded = chunk.ljust(UPLOAD_BLOCK_SIZE, b"\0")
            crc = binascii.crc32(chunk) & 0xFFFFFFFF
            header = UPLOAD_MAGIC + struct.pack("!III", packet_id, len(chunk), crc)

            for attempt in range(3):
                self.sock.sendall(header + padded)
                ack = self.read_packet_ack(packet_id, timeout=8.0)
                response += ack
                break
            if packet_id == 0 or (packet_id + 1) % progress_every == 0:
                percent = ((packet_id + 1) * 100) // total_packets
                print(
                    f"uploaded packet {packet_id + 1}/{total_packets} ({percent}%)",
                    file=sys.stderr,
                    flush=True,
                )

        time.sleep(0.5)
        response += self.command("M29", timeout=30.0)
        if "Done saving file." not in response:
            raise RuntimeError(f"printer did not confirm saved file:\n{response}")
        return response

    def start_print(self, remote_name: str) -> str:
        return self.command(f"M23 {remote_name}") + self.command("M24")


def is_printing(status_text: str) -> bool:
    for line in status_text.splitlines():
        if line.startswith("SD printing byte "):
            try:
                current, total = line.rsplit(" ", 1)[1].split("/", 1)
                return int(total) > 0 and int(current) < int(total)
            except ValueError:
                return True
    return False


def run_status(args: argparse.Namespace) -> int:
    printer = Printer(args.host, args.port)
    acquired = False
    try:
        print(printer.acquire(), end="")
        acquired = True
        print(printer.status(), end="")
        if acquired:
            print(printer.release(), end="")
            acquired = False
    finally:
        if acquired:
            try:
                print(printer.release(), end="")
            except Exception:
                pass
        printer.close()
    return 0


def run_upload(args: argparse.Namespace, *, start: bool) -> int:
    local_path = Path(args.gcode).resolve()
    remote_name = args.remote_name or local_path.name
    printer = Printer(args.host, args.port)
    acquired = False
    try:
        print(printer.acquire(), end="")
        acquired = True
        status_text = printer.status()
        print(status_text, end="")
        if is_printing(status_text):
            raise RuntimeError("printer reports an active SD print; refusing to start another job")

        print(printer.upload(local_path, remote_name), end="")
        if start:
            print(printer.start_print(remote_name), end="")
        if acquired:
            print(printer.release(), end="")
            acquired = False
    finally:
        if acquired:
            try:
                print(printer.release(), end="")
            except Exception:
                pass
        printer.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Printer IP address or hostname")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")

    upload = subparsers.add_parser("upload")
    upload.add_argument("gcode")
    upload.add_argument("remote_name", nargs="?")

    print_cmd = subparsers.add_parser("print")
    print_cmd.add_argument("gcode")
    print_cmd.add_argument("remote_name", nargs="?")

    args = parser.parse_args()
    try:
        if args.command == "status":
            return run_status(args)
        if args.command == "upload":
            return run_upload(args, start=False)
        if args.command == "print":
            return run_upload(args, start=True)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

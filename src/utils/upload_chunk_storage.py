"""Chunk storage utility for resumable upload."""

import json
import os
import shutil
from pathlib import Path
from src.settings import settings


def get_upload_dir(upload_uid: str) -> Path:
    """Get the chunk storage directory for an upload session."""
    return settings.UPLOAD_DIR / ".uploads" / upload_uid


def save_chunk(upload_uid: str, chunk_index: int, data: bytes) -> Path:
    """Save a single chunk to disk."""
    chunk_dir = get_upload_dir(upload_uid)
    os.makedirs(chunk_dir, exist_ok=True)
    chunk_path = chunk_dir / f"chunk_{chunk_index:06d}"
    with open(chunk_path, "wb") as f:
        f.write(data)
    return chunk_path


def read_chunk(upload_uid: str, chunk_index: int) -> bytes:
    """Read a single chunk from disk."""
    chunk_path = get_upload_dir(upload_uid) / f"chunk_{chunk_index:06d}"
    with open(chunk_path, "rb") as f:
        return f.read()


def chunk_exists(upload_uid: str, chunk_index: int) -> bool:
    """Check if a chunk exists on disk."""
    return (get_upload_dir(upload_uid) / f"chunk_{chunk_index:06d}").exists()


def get_chunk_count(upload_uid: str) -> int:
    """Get the number of chunks stored for an upload session."""
    chunk_dir = get_upload_dir(upload_uid)
    if not chunk_dir.exists():
        return 0
    return len([f for f in chunk_dir.iterdir() if f.name.startswith("chunk_")])


def assemble_file(upload_uid: str, total_chunks: int, output_path: Path) -> Path:
    """Assemble all chunks into the final file."""
    os.makedirs(output_path.parent, exist_ok=True)
    with open(output_path, "wb") as out:
        for i in range(total_chunks):
            chunk_data = read_chunk(upload_uid, i)
            out.write(chunk_data)
    return output_path


def cleanup_upload(upload_uid: str) -> None:
    """Remove all chunk files and directory for an upload session."""
    chunk_dir = get_upload_dir(upload_uid)
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)


def get_missing_chunks(received_chunks_str: str, total_chunks: int) -> list:
    """Get list of missing chunk indices."""
    if not received_chunks_str:
        return list(range(total_chunks))
    received = set(json.loads(received_chunks_str))
    return sorted(set(range(total_chunks)) - received)


def mark_chunk_received(received_chunks_str: str, chunk_index: int) -> str:
    """Mark a chunk as received and return updated JSON string."""
    received = set(json.loads(received_chunks_str)) if received_chunks_str else set()
    received.add(chunk_index)
    return json.dumps(sorted(received))

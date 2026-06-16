"""IMAP email attachment importer."""

from __future__ import annotations

import email
import imaplib
from typing import Any


def list_attachments(imap_config: dict[str, Any], folder: str = "INBOX") -> list[dict[str, Any]]:
    """List attachments in the given IMAP folder.

    Parameters
    ----------
    imap_config:
        Dictionary with keys: ``server``, ``port`` (default 993), ``username``, ``password``.
    folder:
        IMAP folder name to search (default ``INBOX``).

    Returns
    -------
    List of dicts with keys: ``msg_id``, ``subject``, ``filename``, ``size``.
    """
    server = imap_config["server"]
    port = int(imap_config.get("port", 993))
    username = imap_config["username"]
    password = imap_config["password"]

    attachments: list[dict[str, Any]] = []
    mail = imaplib.IMAP4_SSL(server, port)
    try:
        mail.login(username, password)
        mail.select(folder)
        _, data = mail.search(None, "ALL")
        msg_ids = data[0].split()

        for msg_id in msg_ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subject = msg.get("Subject", "")
            # Decode subject if needed
            if subject:
                try:
                    decoded, charset = email.header.decode_header(subject)[0]
                    if isinstance(decoded, bytes):
                        subject = decoded.decode(charset or "utf-8", errors="replace")
                    else:
                        subject = decoded
                except Exception:
                    pass

            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                filename = part.get_filename()
                if filename:
                    payload = part.get_payload(decode=True)
                    size = len(payload) if payload else 0
                    attachments.append({
                        "msg_id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                        "subject": subject,
                        "filename": filename,
                        "size": size,
                    })
    finally:
        try:
            mail.close()
        except Exception:
            pass
        try:
            mail.logout()
        except Exception:
            pass

    return attachments


def download_attachment(imap_config: dict[str, Any], msg_id: str, filename: str) -> bytes:
    """Download a specific attachment from an IMAP message.

    Parameters
    ----------
    imap_config:
        Dictionary with keys: ``server``, ``port``, ``username``, ``password``.
    msg_id:
        Message ID (as returned by :func:`list_attachments`).
    filename:
        Attachment filename to retrieve.

    Returns
    -------
    Raw attachment bytes.
    """
    server = imap_config["server"]
    port = int(imap_config.get("port", 993))
    username = imap_config["username"]
    password = imap_config["password"]

    mail = imaplib.IMAP4_SSL(server, port)
    try:
        mail.login(username, password)
        mail.select("INBOX")
        _, msg_data = mail.fetch(msg_id.encode() if isinstance(msg_id, str) else msg_id, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_filename() == filename:
                payload = part.get_payload(decode=True)
                if payload is None:
                    raise RuntimeError(f"附件 {filename} 为空")
                return payload
        raise RuntimeError(f"未在消息 {msg_id} 中找到附件 {filename}")
    finally:
        try:
            mail.close()
        except Exception:
            pass
        try:
            mail.logout()
        except Exception:
            pass

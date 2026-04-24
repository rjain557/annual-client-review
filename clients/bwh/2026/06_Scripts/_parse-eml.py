#!/usr/bin/env python3
"""Parse the three monthly invoice .eml files and dump body + attachment list."""
import base64
import email
import quopri
import re
import sys
from email import policy
from pathlib import Path

HERE = Path(__file__).resolve().parent
INV_DIR = HERE.parent / "05_Invoices"
OUT_DIR = HERE / "monthly-invoice-emails"
OUT_DIR.mkdir(exist_ok=True)

def html_to_text(html):
    html = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', html, flags=re.I)
    html = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=re.I)
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.I)
    html = re.sub(r'</p>', '\n', html, flags=re.I)
    html = re.sub(r'</div>', '\n', html, flags=re.I)
    html = re.sub(r'</tr>', '\n', html, flags=re.I)
    html = re.sub(r'</td>', ' | ', html, flags=re.I)
    html = re.sub(r'</th>', ' | ', html, flags=re.I)
    html = re.sub(r'<[^>]+>', '', html)
    html = html.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&#39;', "'").replace('&quot;', '"')
    html = re.sub(r'\n\s*\n\s*\n', '\n\n', html)
    return html

for eml_path in sorted(INV_DIR.glob("*.eml")):
    print(f"\n{'='*80}\n{eml_path.name}\n{'='*80}")
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    print(f"Subject: {msg['subject']}")
    print(f"From: {msg['from']}")
    print(f"Date: {msg['date']}")
    print(f"To: {msg.get('to', '')}")

    # Body
    body_html = None
    body_text = None
    attachments = []
    for part in msg.walk():
        ct = part.get_content_type()
        disp = str(part.get('Content-Disposition') or '')
        if 'attachment' in disp.lower() or 'inline' in disp.lower() and part.get_filename():
            fn = part.get_filename() or ct
            attachments.append((fn, ct, len(part.get_payload(decode=True) or b'')))
        elif ct == 'text/plain' and body_text is None:
            try:
                body_text = part.get_payload(decode=True).decode(part.get_content_charset('utf-8'), errors='replace')
            except Exception:
                pass
        elif ct == 'text/html' and body_html is None:
            try:
                body_html = part.get_payload(decode=True).decode(part.get_content_charset('utf-8'), errors='replace')
            except Exception:
                pass

    body = body_text or (html_to_text(body_html) if body_html else '')
    print(f"\nAttachments: {len(attachments)}")
    for fn, ct, sz in attachments:
        print(f"  - {fn} ({ct}) {sz} bytes")

    # Save body text
    out_path = OUT_DIR / (eml_path.stem + ".txt")
    out_path.write_text(body, encoding="utf-8")
    print(f"\nBody written to: {out_path}")
    print("\n--- BODY PREVIEW ---")
    # Show a slice with the unpaid-hours table if present
    if 'Unpaid' in body or 'unpaid' in body:
        idx = body.lower().find('unpaid')
        start = max(0, idx - 500)
        end = min(len(body), idx + 3000)
        print(body[start:end])
    else:
        print(body[:3000])

    # Save attachments (we want the xlsx with time entries)
    for part in msg.walk():
        disp = str(part.get('Content-Disposition') or '')
        fn = part.get_filename()
        if fn and ('attachment' in disp.lower() or 'inline' in disp.lower()):
            payload = part.get_payload(decode=True)
            if payload:
                safe = re.sub(r'[^a-zA-Z0-9._-]', '_', fn)
                dest = OUT_DIR / f"{eml_path.stem}__{safe}"
                dest.write_bytes(payload)
                print(f"  saved attachment: {dest.name}")

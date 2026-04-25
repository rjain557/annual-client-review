# User Email Signature — for outbound drafts on behalf of RJain@technijian.com

The two files in this folder hold Ravi Jain's standard Outlook signature, extracted from his Sent Items folder via Microsoft Graph on 2026-04-25:

| File | Use |
|---|---|
| `signature.html` | Append verbatim to HTML email bodies. Contains the embedded headshot, logo, social icons, Bookings links, and Aptos-font styling — exactly as Outlook renders it. |
| `signature.txt` | Plain-text alternative for non-HTML clients. |

## Usage rules

- **The signature begins with `Thank you,`** — body content must end on its last meaningful sentence; do **not** add another closer (`Thanks,`, `Regards,`, `Best,` etc.).
- **Do not hand-write a name + title block** above or inside the body. Use only the file as-is.
- **Title:** CEO. (R. Jain is the CEO; he was excluded from the tech-time-entry-audit drafts run for this reason.)

## Refresh process

If the user updates their Outlook signature, re-pull:

```bash
python _fetch-signature.py    # extracts via heuristic
python _dump-sent-html.py     # dumps raw HTML for manual extraction if heuristic misses
```

## Used by

- `_create-outlook-drafts.py` — creates Graph drafts in `RJain@technijian.com` Drafts folder.
- Future: any email-drafting script in this repo should source these two files.

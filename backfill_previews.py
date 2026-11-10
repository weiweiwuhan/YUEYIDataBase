"""Generate first-page covers for existing documents; safe to run repeatedly."""
import json
import app
from media_preview import backfill_previews

if __name__ == '__main__':
    report = backfill_previews(app.connect, app.execute, app.UPLOADS, app.THUMBS)
    print(json.dumps(report, ensure_ascii=False, indent=2))

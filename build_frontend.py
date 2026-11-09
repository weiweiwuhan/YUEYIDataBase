"""Bundle the offline page into the main script so old servers need no new JS route."""
from pathlib import Path
root=Path(__file__).resolve().parent
marker='\n// OFFLINE_BUNDLE_START\n'
app=root/'static/app.js'
app.write_text(app.read_text('utf-8').split(marker)[0]+marker+(root/'static/offline.js').read_text('utf-8')+'\n// ASSISTANT_BUNDLE_START\n'+(root/'static/assistant.js').read_text('utf-8')+'\n// TECHNICAL_BUNDLE_START\n'+(root/'static/technical.js').read_text('utf-8'),encoding='utf-8')
css=root/'static/style.css'
css_marker='\n/* OFFLINE_BUNDLE_START */\n'
css.write_text(css.read_text('utf-8').split(css_marker)[0]+css_marker+(root/'static/offline.css').read_text('utf-8')+'\n/* ASSISTANT_BUNDLE_START */\n'+(root/'static/assistant.css').read_text('utf-8'),encoding='utf-8')
if __name__=='__main__':print('Frontend bundle updated')

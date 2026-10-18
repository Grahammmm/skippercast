"""Render the small, trusted research Markdown document without dependencies."""
from pathlib import Path
import html
import re
import sys
ROOT = Path(__file__).resolve().parents[2]

def inline(text):
    text=html.escape(text).replace('data-sources.md','sources.html')
    text=re.sub(r'`([^`]+)`',r'<code>\1</code>',text)
    text=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',text)
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',r'<a href="\2">\1</a>',text)

lines=(ROOT/'docs/species-research.md').read_text().splitlines()
out=[];i=0
while i<len(lines):
    line=lines[i];i+=1
    if not line.strip():continue
    if line.startswith('#'):
        n=len(line)-len(line.lstrip('#'));title=line[n:].strip()
        slug=re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-')
        out.append(f'<h{n} id="{slug}">{inline(title)}</h{n}>')
    elif line.startswith('|'):
        rows=[line]
        while i<len(lines) and lines[i].startswith('|'): rows.append(lines[i]);i+=1
        out.append('<div class="forecast-table-wrap"><table><thead><tr>'+''.join('<th>'+inline(c.strip())+'</th>' for c in rows[0].strip('|').split('|'))+'</tr></thead><tbody>')
        for row in rows[2:]:out.append('<tr>'+''.join('<td>'+inline(c.strip())+'</td>' for c in row.strip('|').split('|'))+'</tr>')
        out.append('</tbody></table></div>')
    elif line.startswith('- '):
        rows=[line[2:]]
        while i<len(lines) and lines[i].startswith('- '):rows.append(lines[i][2:]);i+=1
        out.append('<ul>'+''.join('<li>'+inline(r)+'</li>' for r in rows)+'</ul>')
    else:
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','- ')):line+=' '+lines[i];i+=1
        out.append('<p>'+inline(line)+'</p>')
page=('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<title>Species & ocean research · SkipperCast</title><meta name="color-scheme" content="dark"><link rel="icon" href="app-icon.svg">'
      '<!-- FE-61 part 2: the v2 tokens and the readable pages\' sheet (FE-86), as sources.html. -->'
      '<link rel="stylesheet" href="../web/tokens.css"><link rel="stylesheet" href="coast-readable.css"></head>'
      '<body class="coast-readable"><a class="skip-link" href="#content">Skip to content</a><header><a class="brand" href="./">SkipperCast</a>'
      '<nav aria-label="Public information"><a href="/map">Back to the map</a><a href="/sources">Sources &amp; methods</a></nav></header>'
      '<main id="content">'+'\n'.join(out)+'</main></body></html>')
target=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'dist/species-research.html'
target.write_text(page+'\n')

"""Render the small, trusted research Markdown document without dependencies."""
from pathlib import Path
import html
import re
import sys
ROOT = Path(__file__).resolve().parents[2]

def _link(m):
    target=m.group(2);scheme=re.match(r'([A-Za-z][A-Za-z0-9+.-]*):',target)
    bad=target!=target.strip() or any(ord(c)<32 or ord(c)==127 for c in target)
    ok=not bad and (scheme.group(1).lower()=='https' if scheme else target[:2].replace('\\','/')!='//')
    return f'<a href="{target}">{m.group(1)}</a>' if ok else m.group(1)

def inline(text):
    text=html.escape(text).replace('data-sources.md','sources.html')
    text=re.sub(r'`([^`]+)`',r'<code>\1</code>',text)
    text=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',text)
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',_link,text)

def render(markdown_text):
    lines=markdown_text.splitlines()
    out=[];i=0;seen=set()
    while i<len(lines):
        line=lines[i];i+=1
        if not line.strip():continue
        if line.startswith('#'):
            n=len(line)-len(line.lstrip('#'));title=line[n:].strip()
            slug=base=re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-') or 'section';k=1
            while slug in seen:k+=1;slug=f'{base}-{k}'
            seen.add(slug)
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
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<title>Species & ocean research · SkipperCast</title><link rel="canonical" href="https://skippercast.com/species-research.html" /><meta name="color-scheme" content="dark"><link rel="icon" href="app-icon.svg">'
      '<!-- FE-61 part 2: the v2 tokens and the readable pages\' sheet (FE-86), as sources.html. -->'
      '<link rel="stylesheet" href="../web/tokens.css"><link rel="stylesheet" href="coast-readable.css"></head>'
      '<body class="coast-readable"><a class="skip-link" href="#content">Skip to content</a><header><a class="brand" href="./">SkipperCast</a>'
      '<nav aria-label="Public information"><a href="/map">Back to the map</a><a href="/sources">Sources &amp; methods</a></nav></header>'
      '<main id="content">'+'\n'.join(out)+'</main></body></html>')

def main(argv):
    target=Path(argv[0]) if argv else ROOT/'dist/species-research.html'
    target.write_text(render((ROOT/'docs/species-research.md').read_text())+'\n')

if __name__ == '__main__':
    main(sys.argv[1:])

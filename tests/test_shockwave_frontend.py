"""Real Canvas pixels and actual composer clicks; no account/API side effects."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def test_shockwave_feathers_edges_and_finishes_before_removal(tmp_path):
    browser = shutil.which('google-chrome') or shutil.which('chromium')
    if not browser:
        mac = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        browser = str(mac) if mac.exists() else None
    if not browser:
        pytest.skip('Requires Chrome or Chromium for real Canvas pixels')
    root = Path(__file__).resolve().parents[1]
    sources = []
    for name in ['shockwave', 'composer']:
        source = (root / 'static/js' / f'{name}.js').read_text()
        sources.append(re.sub(r'^export ', '', re.sub(r'^import .*;\n', '', source, flags=re.M), flags=re.M))
    script = r'''
const $ = id => document.getElementById(id);
const frames = new Map(); let seq = 0;
window.requestAnimationFrame = fn => { frames.set(++seq, fn); return seq; };
window.cancelAnimationFrame = id => frames.delete(id);
const tick = time => { const [id, fn] = frames.entries().next().value; frames.delete(id); fn(time); };
const assert = (value, msg) => { if (!value) throw new Error(msg); };
initComposer({onSubmit(){}});
try {
  for (const [width, height] of [[1000, 800], [320, 600], [1600, 900]]) {
    $('main').style.width = width + 'px'; $('main').style.height = height + 'px';
    $('hero').replaceWith(Object.assign(document.createElement('section'), {id:'hero'}));
    $('composerInput').click();
    const canvas = $('homeAurora').querySelector('canvas');
    assert(canvas && parseFloat(canvas.style.top) === 0 && parseFloat(canvas.style.left) === 0, 'overlay starts at viewport origin');
    assert(canvas.width===innerWidth && canvas.height===innerHeight, 'canvas covers full viewport regardless of workspace width');
    tick(0); tick(100);
    const ctx = canvas.getContext('2d');
    const pixels = ctx.getImageData(0,0,canvas.width,canvas.height).data;
    let peak = 0;
    for (let i=3;i<pixels.length;i+=4) peak=Math.max(peak,pixels[i]);
    assert(peak>0 && peak<=31, 'visible yet subdued light');
    for(let x=0;x<canvas.width;x++) {
      assert(pixels[x*4+3]===0, 'top edge must fade to zero');
      assert(pixels[((canvas.height-1)*canvas.width+x)*4+3]<=1, 'bottom edge must fade to zero');
    }
    for(let y=0;y<canvas.height;y++) {
      assert(pixels[(y*canvas.width)*4+3]===0, 'left edge must fade to zero');
      assert(pixels[(y*canvas.width+canvas.width-1)*4+3]<=1, 'right edge must fade to zero');
    }
    let leftLit=false, rightLit=false;
    for (const time of [180,300,450,650,850]) {
      tick(time);
      const frame=ctx.getImageData(0,0,canvas.width,canvas.height).data;
      for(let y=0;y<canvas.height;y++) {
        leftLit ||= frame[(y*canvas.width+100)*4+3]>0;
        rightLit ||= frame[(y*canvas.width+canvas.width-100)*4+3]>0;
      }
    }
    assert(leftLit && rightLit,'light must reach sidebar and far-right viewport, outside centered content');
    tick(999);
    const tail=ctx.getImageData(0,0,canvas.width,canvas.height).data;
    assert(!tail.some((value,i)=>i%4===3&&value>1),'light finishes before canvas removal');
    tick(1000);
    assert(!$('homeAurora').children.length && !frames.size, 'no canvas or frame left idle');
    $('composerInput').click();
    assert(!$('homeAurora').children.length,'second click cannot replay');
  }
  $('result').textContent='PASS shockwave pixels and first-click lifecycle';
} catch(error) { $('result').textContent='FAIL '+error.stack; }
'''
    page = tmp_path / 'shockwave.html'
    page.write_text('''<!doctype html><meta charset="utf-8"><style>
body{margin:0}main{position:fixed;left:222px;top:0;width:1000px;height:800px}
.workspace-bar{height:97px}#composerShell{position:absolute;bottom:20px}
</style><main id="main"><div class="workspace-bar"></div><section id="hero"></section>
<form id="composer"><div id="composerShell"><textarea id="composerInput"></textarea></div></form></main>
<div id="homeAurora"></div><pre id="result">PENDING</pre><script>'''
                    + '\n'.join(sources) + script + '</script>')
    result = subprocess.run([browser, '--headless', '--no-sandbox', '--disable-gpu',
                             '--no-first-run', '--disable-background-networking',
                             '--window-size=1920,1080', '--force-device-scale-factor=1',
                             f'--user-data-dir={tmp_path / "browser"}', '--dump-dom', page.as_uri()],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'PASS shockwave pixels and first-click lifecycle' in result.stdout, result.stdout[-3000:]

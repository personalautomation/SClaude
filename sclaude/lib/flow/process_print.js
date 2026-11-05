
const PAPER = {'a4-landscape': [297, 210, 'A4 landscape'], 'a4-portrait': [210, 297, 'A4 portrait'],
  'a3-landscape': [420, 297, 'A3 landscape'], 'a3-portrait': [297, 420, 'A3 portrait']};
const MARGIN = 9, TOP = 12, MARK = 6, OVERLAP = 36, PX = 96 / 25.4;
function cutSheets(paper, scale) {
  const [pw, ph] = PAPER[paper];
  const S = M.sheets;
  // "fit": the whole width on one sheet, the map going on down only.
  if (scale === 'fit') scale = Math.min(1, (pw - 2 * MARGIN) * PX / S.w);
  const w = Math.floor((pw - 2 * MARGIN) * PX / scale), h = Math.floor((ph - TOP - MARGIN - MARK) * PX / scale);
  const starts = []; let start = 0;
  for (;;) {
    starts.push(start);
    const fits = S.cuts.filter((e) => e > start && e <= start + w);
    const end = fits.length ? fits[fits.length - 1] : start + w;
    if (end >= S.w) break;
    start = Math.max(end - OVERLAP, start + 1);
  }
  const cols = starts.length, rows = Math.max(1, Math.ceil((S.h - OVERLAP) / (h - OVERLAP)));
  let out = '';
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const x = starts[c], y = r * (h - OVERLAP), n = r * cols + c + 1;
    let cuts = '';
    const glue = [];
    if (c < cols - 1) { const cx = starts[c + 1] + OVERLAP;
      cuts += '<line x1="' + cx + '" y1="' + y + '" x2="' + cx + '" y2="' + (y + h) + '"/>';
      glue.push('right edge under sheet ' + (n + 1)); }
    if (r < rows - 1) { cuts += '<line x1="' + x + '" y1="' + (y + h - OVERLAP) + '" x2="' + (x + w) + '" y2="' + (y + h - OVERLAP) + '"/>';
      glue.push('bottom edge under sheet ' + (n + cols)); }
    out += '<div class="sheet"><div class="mark"><span>Detailed process — sheet ' + n + ' of ' + rows * cols
      + ' (row ' + (r + 1) + ', column ' + (c + 1) + ')</span><span>'
      + (glue.length ? 'glue the ' + glue.join(', the ') + '; the dashed line is the edge of the overlap' : 'the last sheet')
      + '</span></div><svg viewBox="' + x + ' ' + y + ' ' + w + ' ' + h + '"><use href="#sym-detail" width="'
      + S.w + '" height="' + S.h + '"/><g class="cut">' + cuts + '</g></svg></div>';
  }
  document.getElementById('sheets').innerHTML = out;
  // A deeper top margin: the running header names the section there.
  document.getElementById('pagesize').textContent = '@page{size:' + PAPER[paper][2] + ';margin:' + TOP + 'mm '
    + MARGIN + 'mm ' + MARGIN + 'mm}';
  return rows * cols;
}
function choosePrint() {
  const paper = document.getElementById('paper').value, chosen = document.getElementById('scale').value;
  const scale = chosen === 'fit' ? 'fit' : +chosen;
  const n = cutSheets(paper, scale);
  document.getElementById('count').textContent = n + (n === 1 ? ' sheet' : ' sheets') + ' for the whole process, plus '
    + 'a page for the overview, and the commands';
  try { localStorage.setItem('process-print', JSON.stringify([paper, scale])); } catch (e) {}
}
try { const saved = JSON.parse(localStorage.getItem('process-print') || 'null');
  if (saved) { document.getElementById('paper').value = saved[0]; document.getElementById('scale').value = saved[1]; } } catch (e) {}
document.getElementById('paper').onchange = choosePrint;
document.getElementById('scale').onchange = choosePrint;
document.getElementById('print').onclick = () => window.print();
choosePrint();

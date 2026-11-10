
function dockWidth() {
  const d = document.getElementById('dock');
  if (!d.hidden) document.body.style.setProperty('--dockw', d.offsetWidth + 'px');
}
addEventListener('resize', dockWidth);
function pin(on) {
  document.getElementById('dock').hidden = !on;
  document.body.classList.toggle('pinned', on);
  dockWidth();
  document.querySelectorAll('.pin-head').forEach((b) => { b.textContent = on ? '📌 Unpin' : '📌 Pin'; });
  // A link's own choice (process_url.js) is for that view alone.
  if (!window.processUrlRestoring) try { localStorage.setItem('process-pinned', on ? '1' : '0'); } catch (e) {}
}
let pinned = true;
try { pinned = localStorage.getItem('process-pinned') !== '0'; } catch (e) {}
document.querySelectorAll('.pin').forEach((b) => b.addEventListener('click', () =>
  pin(document.getElementById('dock').hidden)));
pin(pinned);

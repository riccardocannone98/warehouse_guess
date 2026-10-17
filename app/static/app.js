// Tooltip leggero per gli elementi con data-tip (grafici, celle della matrice).
(function () {
  const tip = document.createElement('div');
  tip.className = 'tip';
  tip.hidden = true;
  document.body.appendChild(tip);

  document.addEventListener('mouseover', function (e) {
    const el = e.target.closest('[data-tip]');
    if (!el) { tip.hidden = true; return; }
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
  });
  document.addEventListener('mousemove', function (e) {
    if (tip.hidden) return;
    const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    const y = e.clientY + 16 + tip.offsetHeight > window.innerHeight ? e.clientY - tip.offsetHeight - 10 : e.clientY + 16;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  });
  document.addEventListener('mouseleave', function () { tip.hidden = true; });
})();

// Pulsanti di ricerca: stato "in corso" mentre il server interroga i siti.
document.addEventListener('submit', function (e) {
  const form = e.target;
  if (!form.matches('[data-searching]')) return;
  form.querySelectorAll('button[type=submit]').forEach(function (b) { b.disabled = true; });
  const note = document.getElementById('searching');
  if (note) note.hidden = false;
});

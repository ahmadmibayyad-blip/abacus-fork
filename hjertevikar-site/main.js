// HjerteVikar – shared behaviour
(function () {
  // Mobile menu
  var mb = document.querySelector('.menu-btn'), dr = document.getElementById('drawer');
  if (mb && dr) {
    var setMenu = function (open) {
      dr.hidden = !open;
      mb.setAttribute('aria-expanded', open);
      mb.setAttribute('aria-label', open ? 'Luk menu' : 'Åbn menu');
    };
    mb.addEventListener('click', function () { setMenu(dr.hidden); });
    dr.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !dr.hidden) { setMenu(false); mb.focus(); }
    });
  }

  // Forms (demo: shows confirmation – connect to e-mail/CRM before launch)
  document.querySelectorAll('form.js-form').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!f.checkValidity()) {
        f.classList.add('tried');
        var bad = f.querySelector(':invalid:not(fieldset)');
        if (bad) bad.focus();
        return;
      }
      f.classList.add('sent');
      var ok = f.querySelector('.form-success');
      if (ok) { ok.focus(); ok.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
    });
  });

  // Prefill contact subject from ?emne=
  var emne = new URLSearchParams(location.search).get('emne');
  var sel = document.getElementById('k-emne');
  if (emne && sel) {
    var barn = ['fast-kontaktperson', 'stoetteperson-til-foraeldre', 'samvaer', 'familiebehandling'];
    sel.value = barn.indexOf(emne) > -1 ? 'Ydelse efter Barnets Lov' : 'Ydelse efter Serviceloven';
  }

  // CV upload: show file name + drag & drop
  document.querySelectorAll('input[type=file]').forEach(function (inp) {
    var out = inp.parentElement.querySelector('.file-name');
    var zone = inp.parentElement.querySelector('.upload');
    var show = function () { if (out) out.textContent = inp.files.length ? 'Valgt: ' + inp.files[0].name : ''; };
    inp.addEventListener('change', show);
    if (zone) {
      ['dragenter', 'dragover'].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.add('drag'); }); });
      ['dragleave', 'drop'].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.remove('drag'); }); });
      zone.addEventListener('drop', function (e) { if (e.dataTransfer.files.length) { inp.files = e.dataTransfer.files; show(); } });
    }
  });
})();

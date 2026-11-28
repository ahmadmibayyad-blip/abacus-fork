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

  // ------------------------------------------------------------------
  // Forms -> e-mail via FormSubmit (https://formsubmit.co)
  // After the first submission FormSubmit e-mails an activation link.
  // Once activated, replace the address below with the random alias
  // FormSubmit gives you, so the address is not visible in the code.
  var FORM_INBOX = 'ahmadmibayyad@gmail.com';
  // ------------------------------------------------------------------
  var hidden = function (f, name, value) {
    var i = f.querySelector('input[name="' + name + '"]');
    if (!i) { i = document.createElement('input'); i.type = 'hidden'; i.name = name; f.appendChild(i); }
    i.value = value;
  };
  var showSent = function (f) {
    f.classList.add('sent');
    var ok = f.querySelector('.form-success');
    if (ok) { ok.focus(); ok.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
  };
  var pageUrl = location.href.split(/[?#]/)[0];

  document.querySelectorAll('form.js-form').forEach(function (f, n) {
    // spam honeypot (bots fill it, people never see it)
    var hp = document.createElement('input');
    hp.type = 'text'; hp.name = '_honey'; hp.className = 'hp'; hp.tabIndex = -1;
    hp.setAttribute('autocomplete', 'off'); hp.setAttribute('aria-hidden', 'true');
    f.appendChild(hp);

    // returning from a full-page submit (file upload form)
    if (new URLSearchParams(location.search).get('sendt') === String(n)) showSent(f);

    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!f.checkValidity()) {
        f.classList.add('tried');
        var bad = f.querySelector(':invalid:not(fieldset)');
        if (bad) bad.focus();
        return;
      }
      var err = f.querySelector('.form-error');
      if (err) err.hidden = true;
      hidden(f, '_subject', f.dataset.subject || 'Ny henvendelse – HjerteVikar');
      hidden(f, '_template', 'table');
      hidden(f, 'Side', document.title);

      var btn = f.querySelector('button[type=submit]');
      var file = f.querySelector('input[type=file]');
      if (file && file.files.length) {
        // Attachments need a normal form post; FormSubmit redirects back here.
        hidden(f, '_next', pageUrl + '?sendt=' + n + (f.closest('[id]') ? '#' + f.closest('[id]').id : ''));
        hidden(f, '_captcha', 'false');
        f.action = 'https://formsubmit.co/' + FORM_INBOX;
        btn.setAttribute('aria-busy', 'true');
        HTMLFormElement.prototype.submit.call(f);
        return;
      }

      btn.setAttribute('aria-busy', 'true'); btn.disabled = true;
      fetch('https://formsubmit.co/ajax/' + FORM_INBOX, {
        method: 'POST', headers: { Accept: 'application/json' }, body: new FormData(f)
      }).then(function (r) { return r.json().then(function (j) { return r.ok && String(j.success) !== 'false'; }); })
        .then(function (ok) { if (!ok) throw new Error('send failed'); showSent(f); })
        .catch(function () { if (err) { err.hidden = false; err.focus && err.scrollIntoView({ block: 'center' }); } })
        .then(function () { btn.removeAttribute('aria-busy'); btn.disabled = false; });
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

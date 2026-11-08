/* TANDA: меню, помощник, калькуляторы, фото и осмотр. Без библиотек. */
(function () {
  'use strict';

  /* ---------- Утилиты ---------- */
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const fmt = n => Math.round(Number(n) || 0).toLocaleString('ru-RU');
  function plural(n, f) { const a = Math.abs(n) % 100, b = a % 10; if (a > 10 && a < 20) return f[2]; if (b > 1 && b < 5) return f[1]; if (b === 1) return f[0]; return f[2]; }
  const DAYS = ['день', 'дня', 'дней'];

  function iso(d) { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10); }
  function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function parseDay(s) { const p = String(s || '').split('-').map(Number); return p.length === 3 ? new Date(p[0], p[1] - 1, p[2]) : new Date(NaN); }
  function daysOf(from, to) { const d = Math.round((parseDay(to) - parseDay(from)) / 86400000); return isFinite(d) && d > 0 ? d : 1; }

  function csrf() { const m = $('meta[name="csrf-token"]'); return m ? m.content : ''; }

  /* POST на сервер: JSON или FormData. Ошибку сервера показываем его же текстом. */
  async function post(url, body) {
    const opts = {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf()}};
    if (body instanceof FormData) {
      opts.body = body;
    } else {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body || {});
    }
    let res;
    try { res = await fetch(url, opts); } catch (e) { throw new Error('Нет связи с сайтом. Проверьте интернет и попробуйте ещё раз.'); }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok || !data) throw new Error((data && data.error) || 'Ответа нет. Попробуйте ещё раз.');
    return data;
  }

  /* ---------- Уведомления ---------- */
  function hideLater(t) { setTimeout(() => { t.classList.add('hide'); setTimeout(() => t.remove(), 400); }, 4200); }
  $$('#toasts .toast').forEach(hideLater);

  /* ---------- Мобильное меню ---------- */
  const menu = $('#menu'), menuBtn = $('#menuBtn');
  function openMenu() { menu.classList.add('open'); menuBtn.setAttribute('aria-expanded', 'true'); setTimeout(() => $('#menuClose').focus(), 30); }
  function closeMenu() { menu.classList.remove('open'); menuBtn.setAttribute('aria-expanded', 'false'); }
  if (menu && menuBtn) {
    menuBtn.addEventListener('click', openMenu);
    $('#menuClose').addEventListener('click', closeMenu);
  }

  /* ---------- Подтверждение вторым нажатием («Точно отменить?») ---------- */
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-confirm]');
    if (!b || b.classList.contains('armed')) return;
    e.preventDefault();
    b.dataset.orig = b.textContent;
    b.classList.add('armed');
    b.textContent = b.dataset.confirm;
    setTimeout(() => { if (b.isConnected) { b.classList.remove('armed'); b.textContent = b.dataset.orig; } }, 4000);
  });

  /* ---------- Даты: «по» всегда позже «с» ---------- */
  function linkDates(fromEl, toEl, onChange) {
    if (!fromEl || !toEl) return;
    function fix() {
      const f = fromEl.value;
      if (f) {
        const minTo = iso(addDays(parseDay(f), 1));
        toEl.min = minTo;
        if (!toEl.value || parseDay(toEl.value) <= parseDay(f)) toEl.value = minTo;
      }
      if (onChange) onChange();
    }
    fromEl.addEventListener('change', fix);
    toEl.addEventListener('change', fix);
  }
  const search = $('form.search');
  if (search) linkDates($('[data-date-from]', search), $('[data-date-to]', search));
  $$('[data-autosubmit] select').forEach(s => s.addEventListener('change', () => s.form.submit()));

  /* ---------- Фото: сжимаем в браузере перед отправкой ---------- */
  function fileToCanvas(file, max) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        const k = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
        const cv = document.createElement('canvas');
        cv.width = Math.max(1, Math.round(img.naturalWidth * k));
        cv.height = Math.max(1, Math.round(img.naturalHeight * k));
        cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
        URL.revokeObjectURL(url);
        resolve(cv);
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('bad image')); };
      img.src = url;
    });
  }
  const canvasToBlob = (cv, q) => new Promise(r => cv.toBlob(r, 'image/jpeg', q || .85));
  function thumb(cv, max) {
    const k = Math.min(1, max / Math.max(cv.width, cv.height));
    const t = document.createElement('canvas');
    t.width = Math.max(1, Math.round(cv.width * k)); t.height = Math.max(1, Math.round(cv.height * k));
    t.getContext('2d').drawImage(cv, 0, 0, t.width, t.height);
    return t.toDataURL('image/jpeg', .8);
  }

  $$('[data-file-box]').forEach(box => {
    const input = box.parentElement.querySelector('input[type=file]');
    if (!input) return;
    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      try {
        const cv = await fileToCanvas(file, 1600);
        try {
          const blob = await canvasToBlob(cv, .85);
          if (blob && window.DataTransfer) {
            const dt = new DataTransfer();
            dt.items.add(new File([blob], 'photo.jpg', {type: 'image/jpeg'}));
            input.files = dt.files;
          }
        } catch (e) { /* отправим исходный файл */ }
        box.classList.add('ok');
        box.innerHTML = '<img src="' + thumb(cv, 160) + '" alt="">' + esc(box.dataset.done || 'Фото добавлено. Нажмите, чтобы заменить');
      } catch (e) {
        box.classList.remove('ok');
        box.textContent = 'Не удалось открыть это фото. Загрузите снимок в формате JPG или PNG.';
      }
    });
  });

  /* ---------- Бронирование: пересчёт суммы ---------- */
  const bForm = $('[data-booking]');
  if (bForm) {
    const price = Number(bForm.dataset.price) || 0;
    const feeRate = (Number(bForm.dataset.fee) || 0) / 100;
    const deposit = Number(bForm.dataset.deposit) || 0;
    const calc = $('[data-calc]', bForm);
    const fromEl = $('[data-date-from]', bForm), toEl = $('[data-date-to]', bForm);
    const render = () => {
      const days = daysOf(fromEl.value, toEl.value), sub = price * days, fee = Math.round(sub * feeRate);
      calc.innerHTML =
        '<div><span>' + fmt(price) + ' × ' + days + ' ' + plural(days, DAYS) + '</span><b class="num">' + fmt(sub) + ' сом</b></div>' +
        '<div><span>Сервисный сбор ' + Math.round(feeRate * 100) + '%</span><b class="num">' + fmt(fee) + ' сом</b></div>' +
        '<div class="tot"><span>Итого</span><span class="num">' + fmt(sub + fee) + ' сом</span></div>' +
        (deposit ? '<div class="note"><span>Плюс депозит ' + fmt(deposit) + ' сом, вернём после осмотра</span></div>' : '');
    };
    linkDates(fromEl, toEl, render);
  }

  /* ---------- Сдать машину: заработок, тип транспорта, подсказка ИИ ---------- */
  const earn = $('[data-earn]');
  if (earn) {
    const oForm = $('[data-owner-form]');
    const kindEl = $('[data-earn-kind]'), priceEl = $('[data-earn-price]'), range = $('#eRange');
    const comm = {car: (Number(earn.dataset.commCar) || 20) / 100, van: (Number(earn.dataset.commVan) || 15) / 100};
    const kind = () => (kindEl && kindEl.value === 'van' ? 'van' : 'car');

    const updateEarn = () => {
      const t = kind(), price = Math.max(0, Number(priceEl && priceEl.value) || 0), days = Number(range.value) || 12, c = comm[t];
      const gross = price * days, cut = Math.round(gross * c), net = gross - cut;
      $('[data-earn-days]', earn).textContent = days;
      $('[data-earn-big]', earn).textContent = fmt(net) + ' сом';
      $('[data-earn-text]', earn).textContent = 'при ' + days + ' ' + plural(days, DAYS) + ' аренды в месяц';
      $('[data-earn-calc]', earn).innerHTML =
        '<div><span>Аренда: ' + fmt(price) + ' × ' + days + '</span><b class="num">' + fmt(gross) + ' сом</b></div>' +
        '<div><span>Комиссия TANDA ' + Math.round(c * 100) + '%</span><b class="num">−' + fmt(cut) + ' сом</b></div>' +
        '<div class="tot"><span>Вам</span><span class="num">' + fmt(net) + ' сом</span></div>';
    };

    const updateType = (userChanged) => {
      const t = kind();
      $$('[data-price-label]').forEach(l => { l.textContent = t === 'car' ? 'Цена, сом в сутки' : 'Цена с водителем, сом в день'; });
      $$('.car-only').forEach(el => { el.style.display = t === 'car' ? '' : 'none'; });
      if (userChanged) {
        const seats = oForm && oForm.elements.namedItem('seats');
        if (seats) {
          const n = Number(seats.value);
          if (t === 'car' && n > 9) seats.value = 5;
          if (t === 'van' && (n < 8 || n > 20)) seats.value = 12;
        }
        if (priceEl) {
          const p = Number(priceEl.value);
          if (t === 'car' && p > 9000) priceEl.value = 2500;
          if (t === 'van' && (p < 6000 || p > 16000)) priceEl.value = 9000;
        }
      }
      updateEarn();
    };

    if (kindEl) kindEl.addEventListener('change', () => updateType(true));
    if (priceEl) priceEl.addEventListener('input', updateEarn);
    range.addEventListener('input', updateEarn);
    updateType(false);

    const sBtn = $('[data-suggest]');
    if (oForm && sBtn) {
      const status = $('[data-suggest-status]'), note = $('[data-suggest-note]');
      const field = name => oForm.elements.namedItem(name);
      const say = html => { note.innerHTML = html; note.hidden = false; };
      sBtn.addEventListener('click', async () => {
        const title = field('title').value.trim();
        if (!title) { say('Сначала впишите марку и модель.'); field('title').focus(); return; }
        sBtn.disabled = true;
        status.innerHTML = '<span class="spinner"></span>Сравниваем с похожими объявлениями…';
        try {
          const out = await post(oForm.dataset.suggestUrl, {
            title, kind: kind(), year: field('year').value, city: field('city').value, seats: field('seats').value
          });
          field('price').value = out.price;
          if (out.description) field('description').value = out.description;
          const rng = Array.isArray(out.range) ? ' Похожие машины сдают за ' + fmt(out.range[0]) + '–' + fmt(out.range[1]) + ' сом.' : '';
          say('<b>Рекомендуемая цена: ' + fmt(out.price) + ' сом.</b>' + esc(rng) + ' ' + esc(out.reason || '') + ' Описание добавлено в форму, его можно поправить.');
          updateEarn();
        } catch (e) {
          say(esc(e.message));
        } finally {
          sBtn.disabled = false;
          status.textContent = '';
        }
      });
    }
  }

  /* ---------- Осмотр по фото ---------- */
  const inspectRoot = $('[data-inspect]');
  if (inspectRoot) {
    const insp = {before: null, after: null, afterUrl: null};
    const go = $('#go');
    const showErr = msg => { const el = $('#iErr'); el.textContent = msg; el.classList.add('show'); };
    const hideErr = () => $('#iErr').classList.remove('show');

    $$('[data-slot]', inspectRoot).forEach(slot => {
      const key = slot.dataset.slot, input = $('input', slot);
      async function take(file) {
        if (!file || !/^image\//.test(file.type)) { showErr('Это не похоже на фото. Загрузите изображение JPG или PNG.'); return; }
        hideErr();
        try {
          const cv = await fileToCanvas(file, 1280);
          const blob = await canvasToBlob(cv, .88);
          const url = URL.createObjectURL(blob);
          insp[key] = blob;
          if (key === 'after') insp.afterUrl = url;
          let img = $('img.prev', slot);
          if (!img) { img = document.createElement('img'); img.className = 'prev'; slot.appendChild(img); }
          img.src = url;
          img.alt = key === 'before' ? 'Фото при выдаче' : 'Фото при возврате';
          slot.classList.add('filled');
          $('.ph', slot).style.display = 'none';
          go.disabled = !(insp.before && insp.after);
        } catch (e) { showErr('Не удалось открыть это фото. Попробуйте другое.'); }
      }
      input.addEventListener('change', () => take(input.files[0]));
      slot.addEventListener('dragover', e => { e.preventDefault(); slot.classList.add('drag'); });
      slot.addEventListener('dragleave', () => slot.classList.remove('drag'));
      slot.addEventListener('drop', e => { e.preventDefault(); slot.classList.remove('drag'); take(e.dataTransfer.files[0]); });
    });

    $('#iReset').addEventListener('click', () => {
      insp.before = insp.after = insp.afterUrl = null;
      $$('[data-slot]', inspectRoot).forEach(slot => {
        const img = $('img.prev', slot); if (img) img.remove();
        slot.classList.remove('filled'); $('.ph', slot).style.display = ''; $('input', slot).value = '';
      });
      $('#iResult').classList.remove('show'); $('#iStatus').textContent = ''; hideErr();
      go.disabled = true;
    });

    const sevClass = s => { s = String(s || '').toLowerCase(); return s.indexOf('сер') === 0 ? 's' : s.indexOf('сред') === 0 ? 'm' : 'l'; };

    function renderInspect(out) {
      const dmg = Array.isArray(out.new_damages) ? out.new_damages : [];
      const pill = $('#iPill');
      if (out.same_car === false) { pill.className = 'pill warn'; pill.textContent = 'Похоже, это разные машины'; }
      else if (dmg.length) { pill.className = 'pill bad'; pill.textContent = 'Новых повреждений: ' + dmg.length; }
      else { pill.className = 'pill good'; pill.textContent = 'Новых повреждений нет'; }
      $('#iSummary').textContent = out.summary || '';
      $('#iImg').src = insp.afterUrl;
      const stage = $('#iStage'); $$('.box', stage).forEach(b => b.remove());
      const list = $('#iList'); list.innerHTML = '';
      dmg.forEach((d, i) => {
        if (Array.isArray(d.box) && d.box.length === 4) {
          const [x0, y0, x1, y1] = d.box;
          const el = document.createElement('div'); el.className = 'box';
          el.style.left = (x0 * 100) + '%'; el.style.top = (y0 * 100) + '%';
          el.style.width = Math.max(3, (x1 - x0) * 100) + '%'; el.style.height = Math.max(3, (y1 - y0) * 100) + '%';
          el.innerHTML = '<i>' + (i + 1) + '</i>';
          stage.appendChild(el);
        }
        const it = document.createElement('div'); it.className = 'ditem';
        it.innerHTML = '<div class="dnum">' + (i + 1) + '</div><div><h4>' + esc(d.type || 'Повреждение') + (d.location ? ' · ' + esc(d.location) : '') +
          (d.severity ? '<span class="sev ' + sevClass(d.severity) + '">' + esc(d.severity) + '</span>' : '') + '</h4><p>' + esc(d.description || '') + '</p></div>';
        list.appendChild(it);
      });
      if (!dmg.length) list.innerHTML = '<div class="ditem"><div><h4>Машина в том же состоянии</h4><p>Отличий, похожих на повреждения, нет. Депозит можно вернуть арендатору.</p></div></div>';
      $('#iResult').classList.add('show');
      $('#iResult').scrollIntoView({behavior: 'smooth', block: 'start'});
    }

    go.addEventListener('click', async () => {
      hideErr();
      go.disabled = true;
      $('#iStatus').innerHTML = '<span class="spinner"></span>Сравниваем фото…';
      $('#iResult').classList.remove('show');
      try {
        const fd = new FormData();
        fd.append('before', insp.before, 'before.jpg');
        fd.append('after', insp.after, 'after.jpg');
        renderInspect(await post(inspectRoot.dataset.url, fd));
      } catch (e) {
        showErr(e.message);
      } finally {
        $('#iStatus').textContent = '';
        go.disabled = !(insp.before && insp.after);
      }
    });
  }

  /* ---------- Помощник ---------- */
  const chat = $('#chat');
  if (chat) {
    const GREETING = 'Салам! Напишите, куда едете, сколько вас и на сколько дней. Подберу легковую машину или бусик с водителем и посчитаю стоимость.';
    const msgs = $('#msgs'), input = $('#chatInput'), send = $('#chatSend'), sugs = $('#sugs');
    const hist = [];
    let busy = false;

    const md = t => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^[-•*]\s+/gm, '• ').replace(/\n/g, '<br>');
    const scroll = () => { msgs.scrollTop = msgs.scrollHeight; };
    function addMsg(role, html) {
      const d = document.createElement('div');
      d.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
      d.innerHTML = html;
      msgs.appendChild(d); scroll();
      return d;
    }
    function tripDates() {
      const f = $('[data-date-from]'), t = $('[data-date-to]');
      return {from: f ? f.value : '', to: t ? t.value : ''};
    }
    function setBusy(on) { busy = on; send.disabled = on; input.disabled = on; }

    async function sendChat(text) {
      text = String(text || '').trim();
      if (!text || busy) return;
      setBusy(true);
      sugs.hidden = true;
      addMsg('user', esc(text));
      hist.push({role: 'user', content: text});
      const bubble = addMsg('bot', '<span class="typing" aria-label="Помощник печатает"><i></i><i></i><i></i></span>');
      try {
        const d = tripDates();
        const out = await post(chat.dataset.url, {messages: hist.slice(-12), from: d.from, to: d.to});
        bubble.innerHTML = md(out.reply) + (out.cards || '');
        hist.push({role: 'assistant', content: out.reply + (out.ids && out.ids.length ? '\nIDS: ' + out.ids.join(', ') : '')});
      } catch (e) {
        hist.pop();
        bubble.classList.add('warn');
        bubble.textContent = e.message;
      } finally {
        setBusy(false); scroll(); input.focus();
      }
    }
    function openChat() {
      if (menu && menuBtn) closeMenu();
      chat.classList.add('open');
      setTimeout(() => input.focus(), 60);
    }
    function closeChat() { chat.classList.remove('open'); }

    addMsg('bot', md(GREETING));
    document.addEventListener('click', e => {
      if (e.target.closest('[data-open-chat]')) { e.preventDefault(); openChat(); return; }
      const ask = e.target.closest('[data-ask]');
      if (ask) { e.preventDefault(); openChat(); sendChat(ask.dataset.ask); }
    });
    $('#chatClose').addEventListener('click', closeChat);
    $('#chatForm').addEventListener('submit', e => { e.preventDefault(); const v = input.value; input.value = ''; sendChat(v); });
    sugs.addEventListener('click', e => { const b = e.target.closest('.sug'); if (b) sendChat(b.textContent); });
    const askForm = $('[data-ask-form]');
    if (askForm) {
      askForm.addEventListener('submit', e => {
        e.preventDefault();
        const field = $('input', askForm);
        const q = field.value.trim() || 'Нас 12 человек, едем на Иссык-Куль на 3 дня';
        field.value = '';
        openChat(); sendChat(q);
      });
    }
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      if (menu && menu.classList.contains('open')) closeMenu();
      else if (chat.classList.contains('open')) closeChat();
    });
  }
})();

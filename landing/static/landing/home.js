/* FilmSage landing: small, dependency-free interactions. */
(function () {
  'use strict';

  var doc = document.documentElement;
  doc.classList.add('js');
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- cinematic intro: logo, credit, quote, logo, then the page ---------- */
  (function () {
    var intro = document.getElementById('intro');
    if (!intro) return;
    if (!doc.classList.contains('intro-on')) {
      intro.remove();
      return;
    }
    var STEP = 2700, SHOW = 2200, START = 500, HOLD = 1600;
    var timers = [];
    var hint = document.getElementById('intro-hint');
    // The last scene is the logo again.
    var again = intro.querySelector('.intro__sc').cloneNode(true);
    again.setAttribute('aria-hidden', 'true');
    intro.insertBefore(again, hint);
    var scenes = intro.querySelectorAll('.intro__sc');
    var done = false;

    function leave() {
      if (done) return;
      done = true;
      timers.forEach(clearTimeout);
      try { sessionStorage.setItem('fs-intro', '1'); } catch (e) {}
      intro.classList.add('is-leaving');
      setTimeout(function () {
        doc.classList.remove('intro-on');
        intro.remove();
      }, 900);
    }

    scenes.forEach(function (scene, i) {
      timers.push(setTimeout(function () { scene.classList.add('on'); }, START + i * STEP));
      if (i < scenes.length - 1) {
        timers.push(setTimeout(function () { scene.classList.remove('on'); }, START + i * STEP + SHOW));
      }
    });
    timers.push(setTimeout(leave, START + (scenes.length - 1) * STEP + HOLD));

    intro.addEventListener('click', leave);
    intro.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Escape') {
        e.preventDefault();
        leave();
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') leave();
    });
    intro.focus({ preventScroll: true });
  })();

  /* ---------- reveal sections as they scroll in ---------- */
  var reveals = document.querySelectorAll('[data-reveal]');
  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0.12 });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add('in'); });
  }

  /* ---------- hero wall: loop each column seamlessly ---------- */
  document.querySelectorAll('.wall .track').forEach(function (track) {
    Array.prototype.slice.call(track.children).forEach(function (card) {
      var copy = card.cloneNode(true);
      copy.setAttribute('aria-hidden', 'true');
      track.appendChild(copy);
    });
  });

  /* ---------- feelings: pick up to three ---------- */
  var feels = Array.prototype.slice.call(document.querySelectorAll('.feel'));
  feels.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var on = btn.classList.contains('on');
      var count = feels.filter(function (b) { return b.classList.contains('on'); }).length;
      if (!on && count >= 3) {
        btn.classList.remove('shake');
        void btn.offsetWidth;
        btn.classList.add('shake');
        return;
      }
      btn.classList.toggle('on', !on);
      btn.setAttribute('aria-pressed', String(!on));
    });
  });

  /* ---------- the heart ---------- */
  document.querySelectorAll('.heart--btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var liked = btn.getAttribute('aria-pressed') !== 'true';
      var label = btn.querySelector('span');
      var n = parseInt(label.textContent, 10) + (liked ? 1 : -1);
      label.textContent = n;
      btn.setAttribute('aria-pressed', String(liked));
      btn.setAttribute('aria-label', 'Like, ' + n + ' likes');
      btn.classList.remove('pop');
      void btn.offsetWidth;
      if (liked) btn.classList.add('pop');
    });
  });

  /* ---------- topic types ---------- */
  var types = document.querySelectorAll('.type');
  types.forEach(function (tab) {
    tab.addEventListener('click', function () {
      types.forEach(function (t) {
        var on = t === tab;
        t.classList.toggle('on', on);
        t.setAttribute('aria-selected', String(on));
      });
      document.querySelectorAll('[data-topic]').forEach(function (card) {
        card.hidden = card.getAttribute('data-topic') !== tab.getAttribute('data-type');
      });
    });
  });

  /* ---------- Pick at random: a wall of covers that waves to one ---------- */
  var canvas = document.getElementById('random-wall');
  var dataEl = document.getElementById('random-films');
  if (!canvas || !dataEl) return;
  var films;
  try { films = JSON.parse(dataEl.textContent); } catch (e) { films = []; }
  if (!films.length) return;

  var ctx = canvas.getContext('2d');

  // Each poster loads once: a tiny copy reads as a blurry block on the wall,
  // the full image is the one sharp cover.
  films.forEach(function (f) {
    if (!f.poster) return;
    var img = new Image();
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.onload = function () {
      var tiny = document.createElement('canvas');
      tiny.width = 6; tiny.height = 9;
      tiny.getContext('2d').drawImage(img, 0, 0, 6, 9);
      f.tiny = tiny;
      f.img = img;
    };
    img.src = f.poster;
  });
  var nameEl = document.getElementById('random-name');
  var W = 0, H = 0, dpr = 1, cols = 0, rows = 0, tw = 0, th = 0, oy = 0;
  var finger = null, target = null, glideFrom = null, glideStart = 0;
  var strength = 0, picked = -1, start = performance.now();
  var GLIDE_MS = 900;

  function layout() {
    var r = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = r.width; H = r.height;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.max(12, Math.floor(W / 24));
    tw = W / cols; th = tw * 1.5;
    rows = Math.ceil(H / th) + 1;
    oy = (H - rows * th) / 2;
  }

  function cell(i) {
    return { x: (i % cols) * tw, y: oy + Math.floor(i / cols) * th };
  }
  function nearest(x, y) {
    var c = Math.min(cols - 1, Math.max(0, Math.floor(x / tw)));
    var r = Math.min(rows - 1, Math.max(0, Math.floor((y - oy) / th)));
    return r * cols + c;
  }
  function film(i) { return films[i % films.length]; }

  function roll() {
    var pick = function (n) {
      var lo = Math.floor(n * 0.2), hi = Math.max(lo + 1, Math.ceil(n * 0.75));
      return lo + Math.floor(Math.random() * (hi - lo));
    };
    var t = pick(rows) * cols + pick(cols);
    var c = cell(t);
    target = { x: c.x + tw / 2, y: c.y + th / 2 };
    glideFrom = finger || { x: target.x, y: target.y - th * 3 };
    glideStart = performance.now();
  }

  function moveTo(x, y) {
    target = null;
    finger = { x: x, y: y };
  }

  function pointer(e) {
    var r = canvas.getBoundingClientRect();
    moveTo(e.clientX - r.left, e.clientY - r.top);
  }
  canvas.addEventListener('pointerdown', function (e) {
    canvas.setPointerCapture(e.pointerId);
    pointer(e);
  });
  canvas.addEventListener('pointermove', function (e) {
    if (e.buttons || e.pointerType === 'mouse') pointer(e);
  });
  document.getElementById('random-shuffle').addEventListener('click', roll);

  function draw(now) {
    if (target) {
      var t = Math.min(1, (now - glideStart) / (reduceMotion ? 1 : GLIDE_MS));
      var e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      finger = { x: glideFrom.x + (target.x - glideFrom.x) * e, y: glideFrom.y + (target.y - glideFrom.y) * e };
      if (t === 1) target = null;
    }
    strength += ((finger ? 1 : 0) - strength) * (reduceMotion ? 1 : 0.12);
    var phase = reduceMotion ? 0 : ((now - start) / 2200) * Math.PI * 2;

    ctx.fillStyle = '#14110e';
    ctx.fillRect(0, 0, W, H);

    var radius = tw * 5.5, reach = radius * 1.8;
    var list = [];
    for (var i = 0; i < cols * rows; i++) {
      var c = cell(i), cx = c.x + tw / 2, cy = c.y + th / 2;
      var p = 0, ring = 0, nx = cx, ny = cy, s = 1;
      if (finger) {
        var vx = cx - finger.x, vy = cy - finger.y, d = Math.hypot(vx, vy);
        var dn = d / radius, dr = d / reach;
        p = Math.exp(-dn * dn) * strength;
        var rch = Math.exp(-dr * dr) * strength;
        ring = Math.sin(d / (tw * 1.6) - phase) * rch;
        var ux = d ? vx / d : 0, uy = d ? vy / d : 0;
        nx = finger.x + vx * (1 + 1.2 * p) + ux * ring * tw * 0.5;
        ny = finger.y + vy * (1 + 1.2 * p) + uy * ring * tw * 0.5;
        s = (1 + 2.2 * p) * (1 + 0.18 * ring);
      }
      list.push([i, nx, ny, s, p]);
    }
    list.sort(function (a, b) { return a[3] - b[3]; });

    for (var k = 0; k < list.length; k++) {
      var it = list[k], f = film(it[0]);
      var w = tw * it[3], h = th * it[3], x = it[1] - w / 2, y = it[2] - h / 2;
      roundRect(x, y, w, h, w * 0.14 * it[4]);
      if (f.tiny) {
        ctx.save();
        ctx.clip();
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(f.tiny, x, y, w, h);
        ctx.restore();
      } else {
        var g = ctx.createLinearGradient(x, y, x + w * 0.6, y + h);
        g.addColorStop(0, f.a);
        g.addColorStop(1, f.b);
        ctx.fillStyle = g;
        ctx.fill();
      }
      ctx.fillStyle = 'rgba(0,0,0,' + (0.55 * (1 - it[4])).toFixed(3) + ')';
      ctx.fill();
    }

    if (finger && strength > 0.02) {
      var pi = nearest(finger.x, finger.y);
      if (pi !== picked) {
        picked = pi;
        if (nameEl) nameEl.textContent = film(pi).title;
      }
      var pf = film(pi), pw = tw * 4.4 * strength + tw * (1 - strength), ph = pw * 1.5;
      var px = finger.x - pw / 2, py = finger.y - ph / 2;
      ctx.save();
      ctx.shadowColor = 'rgba(0,0,0,.45)';
      ctx.shadowBlur = 24;
      ctx.shadowOffsetY = 8;
      roundRect(px, py, pw, ph, 8);
      if (pf.img) {
        ctx.fillStyle = '#14110e';
        ctx.fill();
        ctx.shadowColor = 'transparent';
        ctx.clip();
        coverImage(pf.img, px, py, pw, ph);
      } else {
        var pg = ctx.createLinearGradient(px, py, px + pw * 0.6, py + ph);
        pg.addColorStop(0, pf.a);
        pg.addColorStop(1, pf.b);
        ctx.fillStyle = pg;
        ctx.fill();
      }
      ctx.restore();
      // The film's name, as a dark pill above the sharp cover.
      ctx.font = '600 13px Poppins, system-ui, sans-serif';
      var label = pf.title, lw = ctx.measureText(label).width + 26;
      var lx = Math.max(6, Math.min(W - lw - 6, finger.x - lw / 2)), ly = Math.max(6, py - 40);
      ctx.globalAlpha = Math.min(1, strength * 1.2);
      ctx.fillStyle = '#f3efe8';
      roundRect(lx, ly, lw, 30, 15);
      ctx.fill();
      ctx.fillStyle = '#14110e';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, lx + 13, ly + 15);
      ctx.globalAlpha = 1;
    }
    requestAnimationFrame(draw);
  }

  // Draws [img] to fill the box, cropping the overflow like CSS cover.
  function coverImage(img, x, y, w, h) {
    var s = Math.max(w / img.naturalWidth, h / img.naturalHeight);
    var sw = w / s, sh = h / s;
    ctx.drawImage(img, (img.naturalWidth - sw) / 2, (img.naturalHeight - sh) / 2, sw, sh, x, y, w, h);
  }

  function roundRect(x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  layout();
  window.addEventListener('resize', layout);
  // Land on a film when the wall first comes into view.
  if ('IntersectionObserver' in window) {
    var seen = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) { roll(); seen.disconnect(); }
    }, { threshold: 0.4 });
    seen.observe(canvas);
  } else {
    roll();
  }
  requestAnimationFrame(draw);
})();

(() => {
  const root = document.documentElement;
  root.classList.remove('no-js');
  root.classList.add('js');

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const desktop = window.matchMedia('(min-width: 760px)');
  const INTRO_MS = 2200;
  const SEEN_KEY = 'fw-intro-seen';

  const intro = document.getElementById('intro');
  const skip = document.getElementById('intro-skip');
  const page = document.getElementById('page');
  const sticky = document.getElementById('sticky-cta');
  const header = document.querySelector('.site-header');
  const menuToggle = document.querySelector('.menu-toggle');
  const nav = document.getElementById('site-nav');

  const readSeen = () => {
    try {
      return sessionStorage.getItem(SEEN_KEY) === '1';
    } catch (error) {
      return false;
    }
  };

  const writeSeen = () => {
    try {
      sessionStorage.setItem(SEEN_KEY, '1');
    } catch (error) {
      return;
    }
  };

  const markHeroReady = () => root.classList.add('hero-ready');

  let introTimer = 0;

  const endIntro = () => {
    if (!intro || intro.hidden) return;
    clearTimeout(introTimer);
    document.removeEventListener('keydown', onIntroKey);
    intro.hidden = true;
    page.inert = false;
    writeSeen();
    markHeroReady();
  };

  const onIntroKey = (event) => {
    if (event.key === 'Escape') endIntro();
  };

  const introRuns = intro && page && !reduceMotion.matches && !readSeen();
  if (introRuns) {
    intro.hidden = false;
    page.inert = true;
    skip.focus();
    document.addEventListener('keydown', onIntroKey);
    introTimer = setTimeout(endIntro, INTRO_MS);
    skip.addEventListener('click', endIntro);
  } else {
    markHeroReady();
  }

  document.querySelectorAll('[data-stagger]').forEach((list) => {
    [...list.children].forEach((item, index) => {
      item.style.setProperty('--stagger', `${index * 90}ms`);
    });
  });

  const reveals = document.querySelectorAll('[data-reveal]');
  if ('IntersectionObserver' in window && !reduceMotion.matches) {
    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    reveals.forEach((el) => revealObserver.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add('is-in'));
  }

  if (header) {
    let scrolled = null;
    const syncHeader = () => {
      const next = window.scrollY > 8;
      if (next === scrolled) return;
      scrolled = next;
      header.classList.toggle('is-scrolled', next);
    };
    window.addEventListener('scroll', syncHeader, { passive: true });
    syncHeader();
  }

  if (header && menuToggle && nav) {
    const setMenu = (open) => {
      header.classList.toggle('is-open', open);
      menuToggle.setAttribute('aria-expanded', String(open));
    };

    menuToggle.addEventListener('click', () => {
      setMenu(!header.classList.contains('is-open'));
    });

    nav.addEventListener('click', (event) => {
      if (event.target.closest('a')) setMenu(false);
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && header.classList.contains('is-open')) {
        setMenu(false);
        menuToggle.focus();
      }
    });

    desktop.addEventListener('change', () => setMenu(false));
  }

  const hero = document.getElementById('top');
  const finalCta = document.getElementById('get-app');
  const visibility = { heroOut: false, finalIn: false };

  const syncSticky = () => {
    const show = visibility.heroOut && !visibility.finalIn;
    sticky.classList.toggle('is-visible', show);
    sticky.inert = !show;
  };

  if (sticky && hero && finalCta && 'IntersectionObserver' in window) {
    sticky.inert = true;
    const stickyObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.target === hero) visibility.heroOut = !entry.isIntersecting;
        if (entry.target === finalCta) visibility.finalIn = entry.isIntersecting;
      });
      syncSticky();
    });
    stickyObserver.observe(hero);
    stickyObserver.observe(finalCta);
  }
})();

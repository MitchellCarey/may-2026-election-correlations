(function () {
  'use strict';

  const OUTPUT_WIDTH = 2400;
  const BG_COLOUR = '#faf6ec';

  let cssPromise = null;
  function loadSharedCss() {
    if (cssPromise) return cssPromise;
    const href = document.querySelector('link[rel="stylesheet"][href$="shared.css"]');
    const url = href ? href.getAttribute('href') : 'shared.css';
    cssPromise = fetch(url, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error('HTTP ' + r.status))))
      .catch((err) => {
        console.warn('export-png: could not fetch shared.css, exporting without it', err);
        cssPromise = null;
        return '';
      });
    return cssPromise;
  }

  function regionPrefix() {
    return /\/uk(\/|$)/.test(window.location.pathname) ? 'gb' : 'gm';
  }

  function serialiseWithCss(svg, css) {
    const clone = svg.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');

    const vb = (clone.getAttribute('viewBox') || '').split(/\s+/).map(Number);
    if (vb.length === 4 && vb[2] > 0 && vb[3] > 0) {
      const w = OUTPUT_WIDTH;
      const h = Math.round((vb[3] / vb[2]) * OUTPUT_WIDTH);
      clone.setAttribute('width', String(w));
      clone.setAttribute('height', String(h));
    }

    if (css) {
      const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
      style.textContent = css;
      clone.insertBefore(style, clone.firstChild);
    }

    const xml = new XMLSerializer().serializeToString(clone);
    return {
      svgString: xml,
      width: Number(clone.getAttribute('width')) || OUTPUT_WIDTH,
      height: Number(clone.getAttribute('height')) || OUTPUT_WIDTH,
    };
  }

  function rasterise(svgString, width, height) {
    return new Promise((resolve, reject) => {
      const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = BG_COLOUR;
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
        URL.revokeObjectURL(url);
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob returned null'))), 'image/png');
      };
      img.onerror = (e) => {
        URL.revokeObjectURL(url);
        reject(e instanceof Error ? e : new Error('image load failed'));
      };
      img.src = url;
    });
  }

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function handleClick(btn) {
    if (btn.getAttribute('aria-busy') === 'true') return;
    const targetId = btn.dataset.exportTarget;
    const container = targetId ? document.getElementById(targetId) : null;
    const svg = container ? container.querySelector('svg.map-svg') : null;
    if (!svg) {
      console.warn('export-png: no SVG found for target', targetId);
      return;
    }
    const slug = btn.dataset.filenameSlug || targetId || 'map';
    const filename = regionPrefix() + '-' + slug + '.png';

    btn.setAttribute('aria-busy', 'true');
    const originalLabel = btn.textContent;
    btn.textContent = 'Rendering…';
    try {
      const css = await loadSharedCss();
      const { svgString, width, height } = serialiseWithCss(svg, css);
      const blob = await rasterise(svgString, width, height);
      triggerDownload(blob, filename);
    } catch (err) {
      console.error('export-png: render failed', err);
      window.alert("Couldn't render the map. Please try again.");
    } finally {
      btn.removeAttribute('aria-busy');
      btn.textContent = originalLabel;
    }
  }

  function init() {
    const buttons = document.querySelectorAll('button[data-export-png]');
    buttons.forEach((btn) => {
      btn.addEventListener('click', () => handleClick(btn));
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

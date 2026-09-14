'use client';

import { useEffect } from 'react';

export function BrandFavicon() {
  useEffect(() => {
    let disposed = false;
    let frame = 0;
    const mark = new Image();
    const shadow = new Image();
    const probe = document.createElement('span');
    probe.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;background-color:var(--primary)';
    document.body.appendChild(probe);
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 64;
    const context = canvas.getContext('2d');
    const link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/png';
    link.sizes.value = '64x64';
    link.dataset.brandFavicon = 'true';
    function draw() {
      if (disposed || !context || !mark.complete || !mark.naturalWidth || !shadow.complete || !shadow.naturalWidth) return;
      context.clearRect(0, 0, 64, 64);
      context.globalCompositeOperation = 'source-over';
      context.drawImage(mark, 0, 0, 64, 64);
      context.globalCompositeOperation = 'source-in';
      const color = getComputedStyle(probe).backgroundColor;
      context.fillStyle = document.documentElement.classList.contains('dark') ? `color-mix(in srgb, ${color}, white 35%)` : color;
      context.fillRect(0, 0, 64, 64);
      context.globalCompositeOperation = 'source-over';
      context.drawImage(shadow, 0, 0, 64, 64);
      link.href = canvas.toDataURL('image/png');
      document.head.appendChild(link);
    }
    function schedule() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(draw);
    }
    mark.onload = schedule;
    shadow.onload = schedule;
    mark.src = '/brand/origami.png';
    shadow.src = '/brand/origami-shadow.png';
    const observer = new MutationObserver(schedule);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] });
    schedule();
    return () => {
      disposed = true;
      observer.disconnect();
      cancelAnimationFrame(frame);
      link.remove();
      probe.remove();
    };
  }, []);
  return null;
}

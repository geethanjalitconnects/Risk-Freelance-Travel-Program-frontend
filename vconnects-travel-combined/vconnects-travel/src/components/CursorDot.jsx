import { useEffect, useRef } from 'react';

// Orange cursor dot with a trailing ring that grows over interactive elements.
export default function CursorDot() {
  const dot = useRef(null);
  const ring = useRef(null);

  useEffect(() => {
    if (window.matchMedia('(hover: none), (prefers-reduced-motion: reduce)').matches) return undefined;
    let x = -100, y = -100, rx = -100, ry = -100, raf = 0, shown = false;
    const hoverSel = 'a, button, input, select, label, summary, [role="button"], .ride-card';

    const move = (e) => {
      x = e.clientX; y = e.clientY;
      if (!shown) { shown = true; rx = x; ry = y; document.documentElement.classList.add('cursor-on'); }
      ring.current?.classList.toggle('hot', !!e.target.closest?.(hoverSel));
    };
    const leave = () => { shown = false; document.documentElement.classList.remove('cursor-on'); };
    const tick = () => {
      rx += (x - rx) * 0.16;
      ry += (y - ry) * 0.16;
      if (dot.current) dot.current.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      if (ring.current) ring.current.style.transform = `translate3d(${rx}px, ${ry}px, 0)`;
      raf = requestAnimationFrame(tick);
    };
    window.addEventListener('mousemove', move, { passive: true });
    document.addEventListener('mouseleave', leave);
    raf = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener('mousemove', move);
      document.removeEventListener('mouseleave', leave);
      cancelAnimationFrame(raf);
      document.documentElement.classList.remove('cursor-on');
    };
  }, []);

  return (
    <>
      <div className="cursor-ring" ref={ring} aria-hidden="true" />
      <div className="cursor-dot" ref={dot} aria-hidden="true" />
    </>
  );
}

import { useEffect, useState } from 'react';
import { logoUrl } from './Logo.jsx';
import carFront from '../assets/car-front.jpg';

// Intro: dark screen, words rise in, counter runs, an orange panel sweeps up and reveals the page.
export default function Preloader({ onReveal, onDone }) {
  const [phase, setPhase] = useState('in'); // in -> cover -> reveal
  const [count, setCount] = useState(0);

  useEffect(() => {
    document.documentElement.classList.add('is-loading');
    const t1 = setTimeout(() => setPhase('cover'), 2200);
    const t2 = setTimeout(() => { setPhase('reveal'); onReveal(); }, 3000);
    const t3 = setTimeout(() => onDone(), 3950);
    const start = performance.now();
    let raf;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / 2100);
      setCount(Math.round(100 * (1 - Math.pow(1 - t, 3))));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      [t1, t2, t3].forEach(clearTimeout);
      cancelAnimationFrame(raf);
      document.documentElement.classList.remove('is-loading');
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={'preloader ph-' + phase} aria-hidden="true">
      <div className="pl-dark">
        <div className="pl-brand">
          <img src={logoUrl} alt="" />
          <span>VConnects</span>
        </div>
        <img className="pl-car" src={carFront} alt="" />
        <h2 className="pl-title">
          <span className="pl-line"><span style={{ '--i': 0 }}>Travel</span></span>{' '}
          <span className="pl-line"><span style={{ '--i': 1 }}>together.</span></span>
        </h2>
        <p className="pl-sub"><span>Safer carpooling across India</span></p>
        <div className="pl-road"><i /></div>
        <div className="pl-count">{String(count).padStart(3, '0')}</div>
      </div>
      <div className="pl-panel" />
    </div>
  );
}

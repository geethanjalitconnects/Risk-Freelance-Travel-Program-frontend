import { useEffect, useRef } from 'react';
import carFront from '../assets/car-front.jpg';
import { clampProgress } from '../lib/carMotion.js';
import { createCarScene } from '../lib/carScene.js';

// Real 3D car (see lib/carScene.js). Scroll progress through the journey drives the camera
// (front -> top -> rear -> side -> front), the wheel roll and the front-wheel steering.
export default function DrivingCar({ journeyRef }) {
  const hostRef = useRef(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const car = createCarScene(host, { reduce });
    const update = () => {
      const journey = journeyRef.current;
      if (!journey) return;
      const rect = journey.getBoundingClientRect();
      car.setProgress(clampProgress(-rect.top / Math.max(1, rect.height - window.innerHeight)));
    };
    update();
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      car.dispose();
    };
  }, [journeyRef]);

  return (
    <div className="driving-car" role="img" aria-label="White sedan that rolls, steers and turns through front, top, rear and side views as you scroll">
      <div className="driving-car-canvas" ref={hostRef}>
        <img src={carFront} alt="" className="driving-car-fallback" />
      </div>
    </div>
  );
}

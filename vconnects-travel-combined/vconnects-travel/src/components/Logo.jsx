import logoUrl from '../assets/logo.png';

export { logoUrl };

export default function Logo({ light = false }) {
  return (
    <span className={'logo' + (light ? ' logo-light' : '')}>
      <img className="logo-mark" src={logoUrl} alt="" />
      <span className="logo-word">
        V<span>Connects</span>
      </span>
    </span>
  );
}

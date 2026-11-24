import { Link } from '../router.jsx';
import Logo from './Logo.jsx';
import Icon from './Icon.jsx';

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="container footer-top">
        <p>Better journeys.<br />Together.</p>
        <Link to="/publish" className="footer-offer">Share your next ride <Icon name="arrow" size={24} /></Link>
      </div>
      <div className="container footer-grid">
        <div>
          <Logo light />
        </div>
        <div>
          <h4>Travel</h4>
          <Link to="/">Find a ride</Link>
          <Link to="/publish">Publish a ride</Link>
          <Link to="/trips">My trips</Link>
        </div>
        <div>
          <h4>Safety</h4>
          <Link to="/risk-program">Risk program</Link>
          <Link to="/safety">Safety centre</Link>
          <Link to="/profile">Verification &amp; contacts</Link>
        </div>
        <div>
          <h4>Company</h4>
          <Link to="/about">About</Link>
          <Link to="/how-it-works">How it works</Link>
          <Link to="/help">Help &amp; FAQ</Link>
          <Link to="/contact">Contact</Link>
          <Link to="/terms">Terms</Link>
          <Link to="/privacy">Privacy</Link>
        </div>
      </div>
      <div className="container footer-bottom">
        <span>VConnects · Share the road.</span>
        <p>Route incident data and weather in the risk score are illustrative. No payments are taken in the app.</p>
      </div>
    </footer>
  );
}

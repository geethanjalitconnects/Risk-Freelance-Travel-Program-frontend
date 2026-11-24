// Starter Terms and Privacy text. Have these reviewed by a lawyer before going live.
const DOCS = {
  terms: {
    title: 'Terms of use',
    sections: [
      ['Using VConnects', 'VConnects connects drivers with passengers travelling the same way. You must be 18 or older and provide accurate details when you sign up.'],
      ['Drivers', 'Drivers must hold a valid licence, keep their vehicle roadworthy and insured, and only publish rides they intend to make. Fares may not exceed the range shown when publishing.'],
      ['Passengers', 'Passengers must turn up on time, respect the driver and vehicle, and cancel early if plans change.'],
      ['Risk score', 'The trip risk score is guidance based on the factors shown. It does not guarantee safety, and some inputs are illustrative.'],
      ['Payments', 'VConnects does not process payments. Cost sharing is arranged directly between driver and passengers.'],
      ['Emergencies', 'The SOS feature shows helplines and contacts. In an emergency call 112 directly.'],
      ['Changes', 'We may update these terms. Continued use means you accept the updated terms.'],
    ],
  },
  privacy: {
    title: 'Privacy policy',
    sections: [
      ['What we collect', 'Your name, mobile number, gender (optional), verification details, trusted contacts, rides you publish and bookings you make.'],
      ['How we use it', 'To sign you in, match rides, calculate trip risk, run check-ins and SOS, and let drivers and passengers see the details they need for a trip.'],
      ['What others can see', 'Drivers and passengers on the same trip see each other’s name and vehicle details. Trusted contacts see the live trip you share with them.'],
      ['Sign-in tokens', 'Your browser stores sign-in tokens locally so you stay signed in. Signing out removes them.'],
      ['Your choices', 'You can edit your profile and remove trusted contacts at any time. To delete your account, contact us.'],
      ['Contact', 'Questions about privacy can be sent from the Contact page.'],
    ],
  },
};

export default function Legal({ kind }) {
  const doc = DOCS[kind] || DOCS.terms;
  return (
    <div className="container page info-page narrow">
      <h1 className="page-title">{doc.title}</h1>
      <p className="muted">Last updated 17 November 2026</p>
      <div className="panel prose">
        {doc.sections.map(([h, p]) => <section key={h}><h3>{h}</h3><p>{p}</p></section>)}
      </div>
    </div>
  );
}

import React from 'react';
import { createRoot } from 'react-dom/client';
import { Boxes, FileCode2, GitBranch, Network, Route, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import './styles.css';

const features = [
  ['Proxy hosts', 'Create public domains that forward to services on VMs, LXCs, NAS hosts, or containers.', Route],
  ['Coolify-native', 'Leaves Coolify in charge of Traefik, TLS, public entrypoints, and deployments.', Network],
  ['YAML safe', 'Reads and writes one dynamic Traefik file with timestamped backups before every change.', FileCode2],
  ['Settings tab', 'Configure local, SSH, or Proxmox access from the UI or environment variables.', SlidersHorizontal],
  ['Live health', 'Checks the public source and private target so broken routes are visible immediately.', ShieldCheck],
  ['Cubic UI', 'A crisp box-grid interface built for homelabs and small infrastructure teams.', Boxes],
];

function App() {
  return (
    <main>
      <nav className="nav">
        <a className="brand" href="/"><img className="brand-icon" src="/routebox-icon.png" alt="RouteBox icon" /> RouteBox</a>
        <div className="links">
          <a href="#features">Features</a>
          <a href="#icon">Icon</a>
          <a href="https://github.com/arturict/routebox">GitHub</a>
        </div>
      </nav>

      <section className="hero">
        <div>
          <p className="kicker">Coolify Traefik routes</p>
          <h1>Route external services without replacing Coolify.</h1>
          <p className="lead">RouteBox gives Coolify users a minimal cubic control panel for Traefik dynamic YAML: add domains, edit targets, check health, and keep backups.</p>
          <div className="actions">
            <a className="button primary" href="https://github.com/arturict/routebox"><GitBranch size={18} /> View repo</a>
            <a className="button" href="#features">See features</a>
          </div>
        </div>
        <div className="route-card">
          <div className="cube-lines" />
          <div className="route-row active"><span>cloud.example.com</span><b>192.168.1.113:8090</b></div>
          <div className="route-row"><span>media.example.com</span><b>192.168.1.115:8096</b></div>
          <div className="route-row"><span>status.example.com</span><b>192.168.1.113:3002</b></div>
        </div>
      </section>

      <section id="features" className="features">
        {features.map(([title, copy, Icon]) => <article className="feature" key={title}><Icon /><h3>{title}</h3><p>{copy}</p></article>)}
      </section>

      <section id="icon" className="icon-section">
        <div>
          <p className="kicker">Icon direction</p>
          <h2>Minimal, modern, not AI-coded.</h2>
          <p className="lead small">The RouteBox icon should be a flat box or cube outline with a lime route entering and a small orange exit node. No letters, no robot motif, no generic cloud glyph.</p>
        </div>
        <div className="icon-spec">
          <img className="brand-icon big" src="/routebox-icon.png" alt="RouteBox icon" />
          <p>Dark geometric shell. Lime route segment. Orange endpoint. 4-6px corner radius. Strong at favicon size.</p>
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);

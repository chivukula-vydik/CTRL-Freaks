import { NavLink, useLocation } from 'react-router-dom';
import { Icon } from './Icon';

interface Props {
  queueCount?: number;
  targets?: { review?: string; blocked?: string };
}

const links = (t: Props['targets'] = {}) => [
  { to: '/', label: 'Review queue', icon: 'queue' as const, end: true },
  { to: t.review ? `/review/${t.review}` : '/', label: 'Review workspace', icon: 'review' as const, match: '/review' },
  { to: t.blocked ? `/blocked/${t.blocked}` : '/', label: 'Blocked & escalated', icon: 'blocked' as const, match: '/blocked' },
  { to: '/policy', label: 'Policy & content', icon: 'policy' as const },
  { to: '/audit', label: 'Audit & evaluation', icon: 'audit' as const },
];

export function Sidebar({ queueCount, targets }: Props) {
  const { pathname } = useLocation();
  return (
    <nav className="sidebar" aria-label="Primary">
      <div className="brand">
        <div className="brand-mark">
          <Icon name="chat" color="#14171F" strokeWidth={2.2} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span className="brand-name">Engagement Assistant</span>
          <span className="brand-sub">Reviewer console</span>
        </div>
      </div>

      {links(targets).map((l) => (
        <NavLink
          key={l.label}
          to={l.to}
          end={l.end}
          className={({ isActive }) => {
            const onSection = l.match ? pathname.startsWith(l.match) : false;
            // review/blocked links point at '/' until the queue loads; they must not light up with the queue
            return 'nav-link' + ((isActive && (l.end || l.to !== '/')) || onSection ? ' active' : '');
          }}
        >
          <Icon name={l.icon} />
          {l.label}
          {l.end && queueCount !== undefined && <span className="nav-count">{queueCount}</span>}
        </NavLink>
      ))}

      <div className="sidebar-foot">
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="dot" style={{ background: '#E0A03A' }} />
          Mock delivery · draft-only
        </span>
        <span>Synthetic data set v1.2</span>
      </div>
    </nav>
  );
}

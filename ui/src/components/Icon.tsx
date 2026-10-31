import type { CSSProperties, ReactElement } from 'react';

type IconName = 'chat' | 'queue' | 'review' | 'blocked' | 'policy' | 'audit' | 'search' | 'check' | 'x' | 'alert' | 'warn';

const paths: Record<IconName, ReactElement> = {
  chat: <path d="M4 6h16v10H8l-4 4z" />,
  queue: <path d="M4 6h16M4 12h16M4 18h10" />,
  review: (
    <>
      <path d="M4 4h16v16H4z" />
      <path d="M8 9h8M8 13h5" />
    </>
  ),
  blocked: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M6.5 6.5l11 11" />
    </>
  ),
  policy: (
    <>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </>
  ),
  audit: <path d="M5 20V10M12 20V4M19 20v-7" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="M20 20l-4.5-4.5" />
    </>
  ),
  check: <path d="M5 12l5 5 9-10" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  alert: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6M12 16.5v.5" />
    </>
  ),
  warn: (
    <>
      <path d="M12 4l9 16H3z" />
      <path d="M12 10v4M12 17v.5" />
    </>
  ),
};

interface Props {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  color?: string;
  style?: CSSProperties;
}

/** Inline stroke icons. Decorative by default (aria-hidden). */
export function Icon({ name, size = 18, strokeWidth = 2, color = 'currentColor', style }: Props) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flex: 'none', ...style }}
    >
      {paths[name]}
    </svg>
  );
}

'use client';

import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

function USFlag() {
  return (
    <svg width="20" height="14" viewBox="0 0 20 14" style={{ borderRadius: 2, flexShrink: 0 }}>
      <rect width="20" height="14" fill="#B22234" />
      <rect y="2" width="20" height="2" fill="#fff" />
      <rect y="6" width="20" height="2" fill="#fff" />
      <rect y="10" width="20" height="2" fill="#fff" />
      <rect width="8" height="8" fill="#3C3B6E" />
      <g fill="#fff">
        <circle cx="2" cy="1.5" r="0.5" />
        <circle cx="4" cy="1.5" r="0.5" />
        <circle cx="6" cy="1.5" r="0.5" />
        <circle cx="3" cy="3" r="0.5" />
        <circle cx="5" cy="3" r="0.5" />
        <circle cx="2" cy="4.5" r="0.5" />
        <circle cx="4" cy="4.5" r="0.5" />
        <circle cx="6" cy="4.5" r="0.5" />
        <circle cx="3" cy="6" r="0.5" />
        <circle cx="5" cy="6" r="0.5" />
      </g>
    </svg>
  );
}

function CNFlag() {
  return (
    <svg width="20" height="14" viewBox="0 0 20 14" style={{ borderRadius: 2, flexShrink: 0 }}>
      <rect width="20" height="14" fill="#DE2910" />
      <g fill="#FFDE00">
        <polygon points="4,1.5 4.7,3.6 6.9,3.6 5.1,5 5.8,7 4,5.7 2.2,7 2.9,5 1.1,3.6 3.3,3.6" />
        <polygon points="8.5,1 9,1.8 8.5,1.6 8,1.8" />
        <polygon points="10,2.5 10.3,3.3 9.7,2.9 9.3,3.3 9.5,2.5" />
        <polygon points="10,4.5 10.3,5.3 9.7,4.9 9.3,5.3 9.5,4.5" />
        <polygon points="8.5,6 9,6.8 8.5,6.6 8,6.8" />
      </g>
    </svg>
  );
}

const languages = [
  { code: 'en', label: 'EN', flag: <USFlag /> },
  { code: 'zh', label: '中文', flag: <CNFlag /> },
];

export function LanguageDropdown() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { i18n } = useTranslation();

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const current = i18n.language.startsWith('zh') ? languages[1]! : languages[0]!;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-2 py-1.5 font-mono text-[11px] rounded transition-colors w-full"
        style={{
          color: '#EAEAE5',
          background: 'rgba(234,234,229,0.08)',
          border: '1px solid rgba(234,234,229,0.15)',
          cursor: 'pointer',
        }}
      >
        {current.flag}
        <span>{current.label}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ marginLeft: 'auto', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}>
          <path d="M2 4l3 3 3-3" />
        </svg>
      </button>
      {open && (
        <div
          className="absolute left-0 right-0 z-50 rounded overflow-hidden"
          style={{
            bottom: '100%',
            marginBottom: 4,
            backgroundColor: '#1a1a18',
            border: '1px solid rgba(234,234,229,0.15)',
          }}
        >
          {languages.map((lang) => {
            const isActive = lang.code === 'en' ? i18n.language === 'en' : i18n.language.startsWith('zh');
            return (
              <button
                key={lang.code}
                onClick={() => { i18n.changeLanguage(lang.code); setOpen(false); }}
                className="flex items-center gap-2 w-full px-2 py-1.5 font-mono text-[11px] transition-colors"
                style={{
                  color: isActive ? '#EAEAE5' : 'rgba(234,234,229,0.5)',
                  background: isActive ? 'rgba(234,234,229,0.1)' : 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                }}
                onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.backgroundColor = 'rgba(234,234,229,0.06)'; }}
                onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                {lang.flag}
                {lang.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

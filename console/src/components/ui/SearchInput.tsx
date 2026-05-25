'use client';

import { useId } from 'react';

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
  className?: string;
  testId?: string;
}

export default function SearchInput({
  value,
  onChange,
  placeholder = 'Search...',
  label,
  className = '',
  testId,
}: SearchInputProps) {
  const inputId = useId();

  return (
    <div className={className} data-testid={testId}>
      {label && (
        <label
          htmlFor={inputId}
          className="font-mono text-[10px] text-ink-dim uppercase tracking-wider block mb-1"
        >
          {label}
        </label>
      )}
      <div className="relative">
        <svg
          aria-hidden="true"
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-dim"
        >
          <circle cx="7" cy="7" r="5" />
          <path d="M11 11l4 4" />
        </svg>
        <input
          id={inputId}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="h-11 w-full pl-10 pr-4 bg-transparent border border-border font-mono text-[13px] leading-none text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
        />
      </div>
    </div>
  );
}

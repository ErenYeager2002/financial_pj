'use client';
/* Adapted from bytedance/deer-flow @ d3a9c123 (MIT, see ./NOTICE):
   frontend/src/components/ai-elements/conversation.tsx and
   frontend/src/components/workspace/welcome.tsx
   Presentation only. use-stick-to-bottom is NOT ported: the platform
   follow-scroll in ../pi-chat.tsx stays authoritative (audit decision:
   reuse existing scroll behavior instead of a new locked dependency).
   AuroraText gradient replaced with plain foreground text (no new dep). */
import type {HTMLAttributes} from 'react';
import styles from './deerflow-chat.module.css';

export function DeerflowConversation({children, ...rest}: HTMLAttributes<HTMLDivElement>) {
  return <div className={styles.stream} {...rest}><div className={styles.column}>{children}</div></div>;
}

export function DeerflowWelcome({greeting, description, suggestions, onPick}: {
  greeting: string;
  description?: string;
  suggestions?: string[];
  onPick?: (text: string) => void;
}) {
  return (
    <div className={styles.welcome}>
      <div className={styles.welcomeTitle}>
        <span className={styles.welcomeWave} aria-hidden>👋</span>
        <span>{greeting}</span>
      </div>
      {description && <div className={styles.welcomeDesc}>{description}</div>}
      {suggestions && suggestions.length > 0 && (
        <div className={styles.welcomeSuggestions}>
          {suggestions.map(text => (
            <button key={text} type='button' className={styles.welcomeChip} onClick={() => onPick?.(text)}>{text}</button>
          ))}
        </div>
      )}
    </div>
  );
}

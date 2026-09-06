interface HeadingProps {
  title: string;
  description: string;
  level?: 1 | 2;
  compact?: boolean;
}

export function Heading({ title, description, level = 2, compact = false }: HeadingProps) {
  const Title = level === 1 ? 'h1' : 'h2';
  return (
    <div className='min-w-0'>
      <Title className={compact ? 'platform-page-title' : 'text-3xl font-bold tracking-tight'}>{title}</Title>
      {description && <p className='text-muted-foreground text-sm'>{description}</p>}
    </div>
  );
}

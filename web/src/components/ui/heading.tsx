interface HeadingProps {
  title: string;
  description: string;
  level?: 1 | 2;
}

export function Heading({ title, description, level = 2 }: HeadingProps) {
  const Title = level === 1 ? 'h1' : 'h2';
  return (
    <div>
      <Title className='text-3xl font-bold tracking-tight'>{title}</Title>
      <p className='text-muted-foreground text-sm'>{description}</p>
    </div>
  );
}

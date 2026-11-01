import { BookOpen } from 'lucide-react';
import { Button, CardHeader, CodeBlock, PageHeading } from '../../framework/components';
import { messages } from '../../framework/messages';
import { guides } from './guides';

export function HelpPanel({
  selected,
  onSelect,
  onBack,
}: {
  selected: string;
  onSelect: (id: string) => void;
  onBack: () => void;
}) {
  const guide = guides.find((item) => item.id === selected) || guides[0];
  return (
    <>
      <PageHeading
        title={messages.help.title}
        description="Подключение серверов, установка и восстановление."
        actions={<Button onClick={onBack}>{messages.help.back}</Button>}
      />
      <div className="help-layout">
        <nav aria-label={messages.help.contents} className="card help-nav">
          {guides.map((item) => (
            <button
              type="button"
              key={item.id}
              aria-current={item.id === guide.id ? 'page' : undefined}
              className={item.id === guide.id ? 'chosen' : ''}
              onClick={() => onSelect(item.id)}
            >
              {item.title}
            </button>
          ))}
        </nav>
        <article className="card help-article">
          <CardHeader icon={<BookOpen size={18} />} title={guide.title} />
          <div className="guide-content">
            <p>{guide.intro}</p>
            <ol>
              {guide.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
            {guide.code && <CodeBlock key={guide.id} value={guide.code} label={guide.title} />}
            {guide.note && <aside className="guide-note">{guide.note}</aside>}
          </div>
        </article>
      </div>
    </>
  );
}

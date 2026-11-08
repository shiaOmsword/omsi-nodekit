import { useState } from 'react';
import { Play, RefreshCw } from 'lucide-react';
import type { Action, NodeRecord, Plan } from '../../types';
import { Alert, Button, Loading, Modal } from '../../framework/components';
import { actionLabels } from '../../app/format';

export function PlanModal({
  record,
  action,
  plan,
  busy,
  error,
  onClose,
  onReload,
  onLaunch,
}: {
  record: NodeRecord;
  action: Action;
  plan: Plan | null;
  busy: boolean;
  error: string;
  onClose: () => void;
  onReload: () => void;
  onLaunch: () => void;
}) {
  const [tab, setTab] = useState<'steps' | 'files'>('steps');
  const [file, setFile] = useState('');
  const files = Object.keys(plan?.files || {});
  return (
    <Modal
      title={(plan?.options?.inbound?.operation === 'delete' ? 'Удаление inbound' : actionLabels[action].title) + ': план'}
      description={record.name}
      wide
      busy={busy}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button onClick={onReload} disabled={busy} icon={<RefreshCw size={16} />}>
            Обновить план
          </Button>
          <Button
            className={plan?.options?.inbound?.operation === 'delete' ? 'danger-button' : ''}
            variant="primary"
            onClick={onLaunch}
            disabled={!plan}
            loading={busy}
            icon={<Play size={16} />}
          >
            {plan?.options?.inbound?.operation === 'delete' ? 'Удалить inbound' : plan?.options?.subscription_maintenance?.mode === 'clear_server_cache' ? 'Перезапустить 3x-ui' : action === 'tunnel_control' ? (plan?.options?.tunnel_control?.operation === 'disable' ? 'Выключить туннели' : 'Включить туннели') : action === 'xray' ? 'Сохранить в Xray' : action === 'tunnel_route' ? 'Применить маршруты' : action === 'tunnel_restart' ? 'Перезапустить туннели' : 'Запустить операцию'}
          </Button>
        </>
      }
    >
      {error && <Alert tone="error">{error}</Alert>}
      {!plan && busy ? (
        <Loading label="Подготовка плана…" />
      ) : (
        plan && (
          <>
            <div className="plan-context">
              <span
                className={'tag ' + (['fresh', 'restore', 'configure', 'attach_caddy', 'inbound', 'tunnel', 'tunnel_restart', 'tunnel_route', 'tunnel_setup', 'tunnel_control', 'xray', 'xhttp', 'client_import', 'subscription_maintenance', 'tcp_tuning', 'system_restore', 'wireguard'].includes(action) ? 'tag-warning' : '')}
              >
                {['fresh', 'restore', 'configure', 'attach_caddy', 'inbound', 'tunnel', 'tunnel_restart', 'tunnel_route', 'tunnel_setup', 'tunnel_control', 'xray', 'xhttp', 'tcp_tuning', 'system_restore', 'wireguard'].includes(action) || (action === 'subscription_maintenance' && plan.options?.subscription_maintenance?.mode === 'clear_server_cache')
                  ? 'Изменяет сервер'
                  : 'Сервисы на VPS не изменяются'}
              </span>
              <code>{plan.remote_dir}</code>
            </div>
            <div className="page-tabs" role="group" aria-label="Содержимое плана">
              <button
                aria-pressed={tab === 'steps'}
                className={tab === 'steps' ? 'selected' : ''}
                onClick={() => setTab('steps')}
              >
                Действия
              </button>
              <button
                aria-pressed={tab === 'files'}
                className={tab === 'files' ? 'selected' : ''}
                onClick={() => setTab('files')}
                disabled={!files.length}
              >
                Файлы ({files.length})
              </button>
            </div>
            {tab === 'steps' ? (
              <ol className="plan-steps">
                {plan.steps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            ) : (
              <div className="plan-files">
                <div className="file-list">
                  {files.map((name) => (
                    <button
                      key={name}
                      onClick={() => setFile(name)}
                      className={(file || files[0]) === name ? 'selected' : ''}
                    >
                      {name}
                    </button>
                  ))}
                </div>
                <pre tabIndex={0}>{plan.files[file || files[0]]}</pre>
              </div>
            )}
            {['fresh', 'restore'].includes(action) && (
              <p className="feature-hint">
                Существующая панель не перезаписывается. Сервер будет проверен повторно перед
                установкой.
              </p>
            )}
            {action === 'tcp_tuning' && <p className="feature-hint">Изменяется системный алгоритм для новых TCP-сокетов и управляемые Nodekit sysctl/modules-load файлы. Действующие SSH-сессии не переключаются автоматически; для них требуется отдельное переподключение. Чужие файлы конфигурации сохраняются.</p>}
            {action === 'subscription_maintenance' && <p className="feature-hint">
              Аудит читает настройки, DNS и один публичный URL подписки без изменения сервисов.
              Ручной сброс серверного кэша реализован только через перезапуск принадлежащего Nodekit контейнера 3x-ui и может прервать VPN-соединения. Кэш V2BOX, Hiddify, DNS ОС и shared Caddy не затрагиваются.
            </p>}
            {action === 'attach_caddy' && <p className="feature-hint">
              Панель и Xray кратковременно перезапустятся; активные VPN-соединения могут прерваться.
              У исходного Caddy этой ноды будет включён API только на 127.0.0.1:2019 и перезапущен только его контейнер.
              Для общего Caddy добавляется только сайт этой ноды. Существующие inbound, клиенты и чужие сайты сохраняются.
              После успеха обнови обнаружение и создай XHTTP.
            </p>}
            {action === 'configure' && <p className="feature-hint">
              Доступ к панели через Caddy изменяется согласно сохранённому профилю; режим «Только SSH» убирает публичный маршрут панели.
              Панель и Xray кратковременно перезапустятся; активные VPN-соединения могут прерваться. Будет заменён только сохранённый сайт этой ноды в Caddy.
              Существующие inbound и клиенты не редактируются. Разрешённые изменения UFW и публикаций Caddy перечислены в плане.
            </p>}
            {action === 'xhttp' && <p className="feature-hint">Изменяется только управляемый XHTTP inbound и принадлежащие Nodekit маршруты Caddy. Backend остаётся приватным, UFW ограничивается сетью Caddy. У других сайтов Caddy и контейнеров Docker ничего не меняется. Для корректной подписки отдельно проверь Hosts override.</p>}
            {action === 'tunnel_setup' && <p className="feature-hint">Туннели: {plan.options?.tunnel_setup?.names.join(', ')}. Образец для новых выходов: {plan.options?.tunnel_setup?.outbound_tag}. {plan.options?.tunnel_setup?.balancer_tag ? `Балансировщик: ${plan.options.tunnel_setup.balancer_tag}; fallback: ${plan.options.tunnel_setup.fallback_tag}.` : 'Балансировщик создаётся отдельным шагом.'} Существующие маршруты сохраняются. При создании ресурсов Xray перезапустится.</p>}
            {action === 'tunnel_control' && <p className="feature-hint">{plan.options?.tunnel_control?.operation === 'disable' ? 'Выключение' : 'Включение'}: {plan.options?.tunnel_control?.names.join(', ')}. Меняются служба и автозапуск. Выключение прервёт текущие соединения; балансировщик использует оставшиеся выходы или свой fallback.</p>}
            {action === 'xray' && plan.options?.xray?.operation === 'balancer' && <p className="feature-hint">Создать {plan.options.xray.tag}: roundRobin, участники {plan.options.xray.members.join(', ')}, fallback {plan.options.xray.fallback_tag}. При direct трафик после отказа всех участников может выходить через эту VPS. Маршруты inbound сохраняются; Xray перезапустится.</p>}
            {action === 'xray' && plan.options?.xray?.operation === 'route' && <p className="feature-hint">{plan.options.xray.rule_index === undefined ? 'Новое правило в конце таблицы' : `Изменить правило #${plan.options.xray.rule_index + 1}`}: inbound #{plan.options.xray.inbounds.map(i => i.id).join(', #')} → {plan.options.xray.balancer_tag}. Выбранный список заменяется целиком; остальные правила сохраняют свой порядок. Xray перезапустится.</p>}
            {action === 'tunnel_route' && <p className="feature-hint">SSH-выход {plan.options?.tunnel_route?.name}: выбранные inbound #{plan.options?.tunnel_route?.inbounds.map(i => i.id).join(', #')}. Список заменяется целиком. SSH-службы, ключи, европейский outbound и параметры пула сохраняются; Xray может перезапуститься. Снятые inbound возвращаются к остальным правилам, которые могут вести в direct.</p>}
            {action === 'tunnel_restart' && <p className="feature-hint">Будут последовательно перезапущены SSH-туннели: {plan.options?.tunnel_restart?.names.join(', ')}. VPN-трафик через них кратковременно прервётся. Xray, Caddy, маршруты, ключи и автозапуск сохраняются. При ошибке операция остановится; уже перезапущенные соединения не откатываются.</p>}
            {action === 'tunnel' && plan.options?.tunnel?.members?.length && <p className="feature-hint">Пул поднимет несколько независимых systemd SSH-процессов и создаст roundRobin с observatory и fallback=blocked. Один общий выходной сервер не заменяет независимое резервирование. Xray будет перезапущен.</p>}
            {action === 'tunnel' && !plan.options?.tunnel?.members?.length && <p className="feature-hint">Будет включена systemd-служба SSH и добавлен маршрут для всех клиентов выбранного inbound. Xray перезапустится. UUID и ключи сохраняются; при ошибке выполняется откат. Ключ и known_hosts должны быть подготовлены на московской VPS.</p>}
            {action === 'client_import' && <p className="feature-hint">Из проверенного SQLite импортируются выбранные UUID и subId. Если включено восстановление связанных подписок, дополнительный шаг добавит недостающие HTTPS-ссылки на других клиентов из этой же базы через Clients API (без замены существующих чужих связей). Перед записью создаётся снимок целевой базы; Caddy и SSH не меняются.</p>}
            {action === 'traffic' && <p className="feature-hint">Будет запущен временный Xray-клиент на loopback VPS. Его конфигурация с секретами удалится после проверки. Маршруты сервера не меняются; пробный трафик учитывается у выбранного клиента.</p>}
            {action === 'inbound' && <p className="feature-hint">Перед изменением проверяется актуальность inbound и сохраняется SQLite snapshot на VPS. Удаление удаляет также его клиентов; при редактировании их идентификаторы и ключи сохраняются.</p>}
          </>
        )
      )}
    </Modal>
  );
}

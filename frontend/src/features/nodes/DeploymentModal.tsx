import { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { DeploymentTarget, InstallationReport, NodeRecord, RestoreProfile } from '../../types';
import { api, getErrorMessage } from '../../api';
import { defaultTarget, readConfig, writeConfig } from '../../app/config';
import { Button, FormDialog, FormFields } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function DeploymentModal({
  record,
  report,
  backupId,
  busy,
  error,
  onClose,
  onSave,
}: {
  record: NodeRecord;
  report: InstallationReport | null;
  backupId?: string;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (yaml: string) => void;
}) {
  const source = readConfig(record.yaml);
  const [profile, setProfile] = useState<RestoreProfile | null>(null);
  const [profileError, setProfileError] = useState('');
  const [profileLoading, setProfileLoading] = useState(!!backupId);
  useEffect(() => {
    setProfile(null); setProfileError(''); setProfileLoading(!!backupId);
    if (!backupId) return;
    const controller = new AbortController();
    api<RestoreProfile>('/backups/' + encodeURIComponent(backupId) + '/restore-profile', { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setProfile(result); })
      .catch(error => { if (!controller.signal.aborted) setProfileError(getErrorMessage(error)); })
      .finally(() => { if (!controller.signal.aborted) setProfileLoading(false); });
    return () => controller.abort();
  }, [backupId]);
  const observed = new Set(report?.panels.flatMap((p) => (p.inbounds || []).map((i) => i.nodekit_name ||
    (i.remark.startsWith('nodekit:' + record.id + ':') ? i.remark.slice(('nodekit:' + record.id + ':').length) : ''))) || []);
  const [target, setTarget] = useState<DeploymentTarget>(
    () => ({ ...defaultTarget(), ...source.deployment, inbounds: (source.deployment?.inbounds || []).filter((i) => !observed.has(i.name)) }),
  );
  const [values, setValues] = useState<FormValues>({
    role: target.role,
    runtime: target.panel_runtime,
    caddy: target.caddy_mode,
    caddy_id: report?.caddy.find((p) => p.id === target.caddy_id || 'docker:' + p.container === target.caddy_id)?.id || target.caddy_id || '',
    domain: source.caddy?.domain || '',
    https_port: String(source.caddy?.https_port || 2096),
    subscription_port: String(source.panel?.subscription_port || 2097),
    install_docker: target.install_docker,
    manage_ufw: target.manage_ufw ?? true,
    manage_caddy_ports: target.manage_caddy_ports ?? true,
  });
  const proxies = report?.caddy || [];
  const installed = !!report?.panels.some((p) => p.installation === 'managed' && p.active);
  const selectedProxy = proxies.find((p) => p.id === values.caddy_id);
  const unpublished = values.caddy === 'existing' && selectedProxy?.installation === 'docker' &&
    selectedProxy.network_mode !== 'host' && !selectedProxy.published_ports.some((p) =>
      p.endsWith(`:${Number(values.https_port)}->${Number(values.https_port)}/tcp`));
  const fields: FormField[] = [
    { name: 'manage_ufw', label: 'Настраивать правила UFW для ноды', type: 'checkbox',
      hint: 'Только активный UFW: порты inbound, HTTPS/ACME и доступ Docker Caddy к подпискам. UFW не включается и не сбрасывается.' },
    ...(values.caddy === 'existing' ? [{ name: 'manage_caddy_ports', label: 'Добавлять недостающие порты общего Caddy', type: 'checkbox',
      hint: 'Минимальный Compose override; контейнер Caddy может быть кратковременно пересоздан. Остальные настройки и сервисы сохраняются.' } as FormField] : []),
    {
      name: 'role',
      label: 'Роль ноды',
      type: 'select',
      options: [
        { value: 'exit', label: 'Выходная (Европа / другие регионы)' },
        { value: 'ingress', label: 'Входная (Москва / РФ)' },
      ],
    },
    {
      name: 'runtime',
      label: 'Где установить 3x-ui',
      type: 'select',
      disabled: installed,
      hint: installed ? 'Панель уже установлена. Эта операция не переносит её между Docker и systemd.' : undefined,
      options: [
        { value: 'docker', label: 'Docker Compose · рекомендуется' },
        { value: 'native', label: 'В системе · systemd' },
      ],
    },
    { name: 'subscription_port', label: 'Внутренний порт подписок 3x-ui', type: 'number',
      required: true, min: 1, max: 65535,
      hint: 'Например, 2097. Caddy принимает HTTPS на своём порту и передаёт запрос сюда по HTTP.' },
    {
      name: 'caddy',
      label: 'HTTPS для подписок',
      type: 'select',
      options: [
        { value: 'none', label: 'Без Caddy · доступ через SSH' },
        { value: 'docker', label: 'Новый Caddy в Docker' },
        { value: 'existing', label: 'Использовать общий Caddy' },
      ],
    },
    ...(values.caddy === 'existing'
      ? [
          {
            name: 'caddy_id',
            label: 'Найденный Caddy',
            type: 'select',
            required: true,
            options: [
              { value: '', label: 'Выбери экземпляр' },
              ...proxies.map((p) => ({ value: p.id, label: p.container || p.service || p.id })),
              ...(target.caddy_id && !proxies.some((p) => p.id === target.caddy_id)
                ? [{ value: target.caddy_id, label: 'Сохранённый: ' + target.caddy_id }]
                : []),
            ],
            hint: !proxies.length ? 'Для нового выбора сначала запусти обнаружение.' : undefined,
          } as FormField,
        ]
      : []),
    ...(values.caddy !== 'none'
      ? ([
          {
            name: 'domain',
            label: 'Домен подписок',
            required: true,
            placeholder: 'sub.example.com',
          },
          {
            name: 'https_port',
            label: 'HTTPS-порт Caddy',
            type: 'number',
            required: true,
            min: 1,
            max: 65535,
          },
        ] as FormField[])
      : []),
    ...(values.runtime === 'docker' || values.caddy === 'docker'
      ? [
          {
            name: 'install_docker',
            label: 'Установить Docker, если отсутствует',
            type: 'checkbox',
            hint: 'Ubuntu/Debian: пакеты docker.io и docker-compose-v2.',
          } as FormField,
        ]
      : []),
  ];
  function change(name: string, value: string | boolean) {
    setValues((v) => {
      const next = { ...v, [name]: value };
      if (name === 'caddy_id') {
        const proxy = proxies.find((p) => p.id === value);
        if (
          proxy?.network_mode !== 'host' &&
          proxy?.published_ports.some((p) => p.endsWith(':443->443/tcp'))
        )
          next.https_port = '443';
      }
      return next;
    });
  }
  function addInbound() {
    let index = 1;
    while (target.inbounds.some((i) => i.name === 'ssh-' + index)) index++;
    const occupied = new Set([
      ...target.inbounds.map((i) => i.port),
      ...(report?.panels.flatMap((p) => (p.inbounds || []).map((i) => i.port)) || []),
      Number(source.panel?.port || 2053), Number(values.subscription_port),
    ]);
    for (const proxy of proxies.filter((p) => p.active)) {
      for (const publication of proxy.published_ports) {
        const match = publication.match(/:(\d+)->\d+\/(?:tcp|udp)$/);
        if (match) occupied.add(Number(match[1]));
      }
      for (const route of proxy.routes || []) {
        for (const listener of route.listen) {
          const match = listener.match(/:(\d+)$/);
          if (match) occupied.add(Number(match[1]));
        }
      }
    }
    if (values.caddy !== 'none') occupied.add(Number(values.https_port));
    const port = [443, 8443, 8444, 8445, 9443].find((p) => !occupied.has(p)) || 10443 + index;
    setTarget((t) => ({
      ...t,
      inbounds: [
        ...t.inbounds,
        { name: 'ssh-' + index, port, listen: values.role === 'ingress' ? '0.0.0.0' : '127.0.0.1', server_name: '', target_port: 443, client_email: 'client-' + index },
      ],
    }));
  }
  function submit() {
    if (backupId && !profile) return;
    const data = readConfig(record.yaml);
    const proxy = proxies.find((p) => p.id === values.caddy_id);
    const bind =
      values.caddy === 'existing'
        ? proxy
          ? proxy.installation === 'docker' && proxy.network_mode !== 'host'
            ? proxy.host_gateway || ''
            : '127.0.0.1'
          : target.subscription_bind
        : '127.0.0.1';
    data.deployment = {
      ...target,
      role: values.role as 'exit',
      panel_runtime: values.runtime as 'native',
      caddy_mode: values.caddy as 'none',
      caddy_id: values.caddy === 'existing' ? (proxy?.installation === 'docker' && proxy.container ? 'docker:' + proxy.container : String(values.caddy_id)) : null,
      subscription_bind: bind,
      install_docker:
        (values.runtime === 'docker' || values.caddy === 'docker') && !!values.install_docker,
      inbounds: target.inbounds.map((inbound) => ({ ...inbound, client_email: inbound.client_email || null })),
      manage_ufw: !!values.manage_ufw,
      manage_caddy_ports: !!values.manage_caddy_ports,
    };
    data.panel = { ...data.panel, installation: 'managed', container: null, database_path: null,
      subscription_port: Number(values.subscription_port), ...(profile || {}) };
    data.caddy = {
      ...data.caddy,
      enabled: values.caddy !== 'none',
      ...(values.caddy === 'none' ? { panel_access: { mode: 'disabled' as const } } : {}),
      domain: String(values.domain) || 'vpn.example.com',
      https_port: Number(values.https_port),
    };
    if (proxy?.config_path) data.caddy.config_path = proxy.config_path;
    if (proxy?.service) data.caddy.service = proxy.service;
    onSave(writeConfig(data));
  }
  return (
    <FormDialog
      title={backupId ? "Параметры восстановления" : "Параметры установки"}
      description={record.name + (installed ? ' · настройки установленной панели' : ' · новая установка или восстановление')}
      fields={fields}
      values={values}
      onChange={change}
      onSubmit={submit}
      onClose={onClose}
      busy={busy || profileLoading}
      error={error || profileError}
      submit="Сохранить параметры"
    >
      {!installed && <p><Button onClick={() => setValues(v => ({ ...v, runtime: 'docker', caddy: v.caddy === 'existing' && selectedProxy?.active ? 'existing' : 'docker' }))}>Docker + Caddy · рекомендуемый вариант</Button></p>}
      {backupId && <div className="form-section"><h3>Пути из выбранного бэкапа</h3>
        {profile ? <p>Панель: <code>{profile.base_path}</code> · подписки: <code>{profile.subscription_path}</code>. Сохраняются для совместимости с существующими ссылками.</p> : <p>{profileLoading ? 'Читаю пути из выбранного бэкапа…' : 'Не удалось получить пути; сохранение заблокировано до успешного чтения выбранного бэкапа.'}</p>}
        <p className="feature-hint">Источник SQLite может быть native или Docker. Окружение назначения выбирается выше; клиенты, WG-ключи и маршруты остаются в базе. Установка возможна на пустую цель.</p>
      </div>}
      {!source.deployment && <p className="feature-hint">Для новой установки рекомендуется Docker + Caddy. Native и работа без Caddy доступны для явного выбора.</p>}
      {values.caddy !== 'none' && <div className="form-section">
        <h3>Публичный адрес подписок</h3>
        <code className="subscription-template">https://{String(values.domain) || 'домен'}{Number(values.https_port) === 443 ? '' : ':' + values.https_port}{source.panel?.subscription_path || '/sub/'}&lt;ID подписки&gt;</code>
        {selectedProxy && <p className="feature-hint">Опубликовано в Caddy: {selectedProxy.published_ports.join(', ') || 'нет публикаций / сеть хоста'}</p>}
        {unpublished && <p className="report-warning">Порт {String(values.https_port)} не опубликован в общем Caddy.
          {' '}Требуется {String(values.https_port)}:{String(values.https_port)}/tcp.
          {values.manage_caddy_ports ? ' Nodekit проверит Compose-проект и добавит публикацию через свой override; потребуется короткое пересоздание Caddy.' : ' Добавь публикацию в Compose или включи автоматическое согласование портов.'}</p>}
        {installed && <p className="feature-hint">Сохранение меняет локальные параметры. Если Caddy ещё не подключён к панели, сначала выполни операцию «Подключить Caddy». Для дальнейших изменений открой «Подписки и inbound».</p>}
      </div>}
      <div className="form-section">
        <div className="section-heading compact">
          <div>
            <h3>VLESS / REALITY inbound</h3>
            {installed && <p className="feature-hint">Здесь задаются новые inbound. Существующие изменяются и удаляются на вкладке «Inbound».</p>}
              <p>Каждый новый inbound получает первого клиента и ID подписки. Для выхода через SSH выбери 127.0.0.1; для прямого подключения — публичный listener.</p>
          </div>
          <Button
            small
            onClick={addInbound}
            disabled={target.inbounds.length >= 12}
            icon={<Plus size={16} />}
          >
            Добавить
          </Button>
        </div>
        {!target.inbounds.length && (
          <p className="feature-hint">Inbound не заданы. При Fresh будет создана пустая панель. При применении настроек существующие inbound сохраняются.</p>
        )}
        {target.inbounds.map((inbound, index) => (
          <div className="inbound-form" key={index}>
            <div className="inbound-heading">
              <strong>Inbound {index + 1}</strong>
              <button
                type="button"
                className="icon-button"
                aria-label={'Удалить inbound ' + (index + 1)}
                onClick={() =>
                  setTarget((t) => ({ ...t, inbounds: t.inbounds.filter((_, i) => i !== index) }))
                }
              >
                <Trash2 size={17} />
              </button>
            </div>
            <FormFields
              fields={[
                { name: 'name', label: 'Имя', required: true, pattern: '[a-z][a-z0-9\\-]{0,31}' },
                { name: 'client_email', label: 'Имя первого клиента', maxLength: 80,
                  pattern: '[a-zA-Z0-9][a-zA-Z0-9_.@\\-]{0,79}',
                  hint: 'Только для нового inbound; существующие клиенты не переименовываются.' },
                {
                  name: 'port',
                  label: 'Порт inbound',
                  type: 'number',
                  required: true,
                  min: 1,
                  max: 65535,
                },
                {
                  name: 'server_name',
                  label: 'REALITY SNI',
                  required: true,
                  placeholder: 'www.example.com',
                },
                {
                  name: 'target_port',
                  label: 'Порт REALITY target',
                  type: 'number',
                  required: true,
                  min: 1,
                  max: 65535,
                },
                {
                  name: 'listen',
                  label: 'Принимать соединения',
                  type: 'select',
                  options: [
                    { value: '127.0.0.1', label: 'Только SSH-туннель · 127.0.0.1' },
                    { value: '0.0.0.0', label: 'Публично · 0.0.0.0' },
                  ],
                },
              ]}
              values={{
                ...inbound,
                client_email: inbound.client_email || '',
                port: String(inbound.port),
                target_port: String(inbound.target_port),
              }}
              onChange={(name, value) =>
                setTarget((t) => ({
                  ...t,
                  inbounds: t.inbounds.map((v, i) =>
                    i === index
                      ? {
                          ...v,
                          [name]: name === 'port' || name === 'target_port' ? Number(value) : value,
                        }
                      : v,
                  ),
                }))
              }
            />
          </div>
        ))}
        <p className="feature-hint">
          UUID и ключи создаются на сервере. При Restore сохраняются клиенты из бэкапа; этот список
          не добавляет новые inbound. При «Подписки и inbound» создаются только недостающие записи Nodekit.
          Ссылки сохраняются на VPS в закрытом файле subscriptions.json.
        </p>
      </div>
    </FormDialog>
  );
}

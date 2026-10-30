import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { DeploymentTarget, InstallationReport, NodeRecord } from '../../types';
import { defaultTarget, readConfig, writeConfig } from '../../app/config';
import { Button, FormDialog, FormFields } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function DeploymentModal({
  record,
  report,
  busy,
  error,
  onClose,
  onSave,
}: {
  record: NodeRecord;
  report: InstallationReport | null;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (yaml: string) => void;
}) {
  const source = readConfig(record.yaml);
  const [target, setTarget] = useState<DeploymentTarget>(
    () => source.deployment || defaultTarget(),
  );
  const [values, setValues] = useState<FormValues>({
    role: target.role,
    runtime: target.panel_runtime,
    caddy: target.caddy_mode,
    caddy_id: target.caddy_id || '',
    domain: source.caddy?.domain || '',
    https_port: String(source.caddy?.https_port || 2096),
    install_docker: target.install_docker,
  });
  const proxies = report?.caddy || [];
  const fields: FormField[] = [
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
      options: [
        { value: 'native', label: 'В системе · systemd' },
        { value: 'docker', label: 'Docker Compose' },
      ],
    },
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
      if (name === 'role') next.runtime = value === 'exit' ? 'native' : 'docker';
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
    const occupied = new Set(target.inbounds.map((i) => i.port));
    if (values.caddy !== 'none') occupied.add(Number(values.https_port));
    const port = [443, 8443, 8444, 8445, 9443].find((p) => !occupied.has(p)) || 10443 + index;
    setTarget((t) => ({
      ...t,
      inbounds: [
        ...t.inbounds,
        { name: 'ssh-' + index, port, listen: '127.0.0.1', server_name: '', target_port: 443 },
      ],
    }));
  }
  function submit() {
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
      caddy_id: values.caddy === 'existing' ? String(values.caddy_id) : null,
      subscription_bind: bind,
      install_docker:
        (values.runtime === 'docker' || values.caddy === 'docker') && !!values.install_docker,
    };
    data.panel = { ...data.panel, installation: 'managed', container: null, database_path: null };
    data.caddy = {
      ...data.caddy,
      enabled: values.caddy !== 'none',
      domain: String(values.domain) || 'vpn.example.com',
      https_port: Number(values.https_port),
    };
    if (proxy?.config_path) data.caddy.config_path = proxy.config_path;
    if (proxy?.service) data.caddy.service = proxy.service;
    onSave(writeConfig(data));
  }
  return (
    <FormDialog
      title="Параметры установки"
      description={record.name + ' · новая установка или восстановление'}
      fields={fields}
      values={values}
      onChange={change}
      onSubmit={submit}
      onClose={onClose}
      busy={busy}
      error={error}
      submit="Сохранить параметры"
    >
      <div className="form-section">
        <div className="section-heading compact">
          <div>
            <h3>VLESS / REALITY inbound</h3>
            <p>Для SSH-туннелей с входных нод.</p>
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
          <p className="feature-hint">Inbound не заданы. При Fresh будет создана пустая панель.</p>
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
          не добавляет новые inbound.
        </p>
      </div>
    </FormDialog>
  );
}

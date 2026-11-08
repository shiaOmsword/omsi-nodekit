import { useState } from 'react';
import type { Action, InstallationReport, NodeRecord } from '../../types';
import { readConfig, writeConfig } from '../../app/config';
import type { PanelAccessConfig } from '../../app/config';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function PanelAccessModal({ record, report, busy, error, onClose, onSave }: {
  record: NodeRecord; report: InstallationReport; busy: boolean; error: string;
  onClose: () => void; onSave: (yaml: string, action: Action) => Promise<void>;
}) {
  const source = readConfig(record.yaml);
  const previous = source.caddy?.panel_access;
  const target = source.deployment;
  const proxies = report.caddy;
  const selected = proxies.find(p => p.id === target?.caddy_id || 'docker:' + p.container === target?.caddy_id);
  const [values, setValues] = useState<FormValues>({ mode: previous?.mode || 'disabled', username: previous?.username || '', password: '',
    allowed_ips: previous?.allowed_ips?.join('\n') || '', caddy_id: selected?.id || (proxies.length === 1 ? proxies[0].id : ''), confirm: false });
  const [working, setWorking] = useState(false);
  const [validation, setValidation] = useState('');
  const fields: FormField[] = [
    { name: 'mode', label: 'Доступ к 3x-ui через HTTPS', type: 'select', required: true, options: [
      { value: 'disabled', label: 'Только SSH · публичный вход закрыт' },
      { value: 'basic_auth', label: 'Дополнительный логин и пароль' },
      { value: 'ip_allowlist', label: 'Только разрешённые IP / сети' },
    ] },
    { name: 'caddy_id', label: 'Caddy для входа в панель', type: 'select', required: true, disabled: target?.caddy_mode === 'existing',
      options: [{ value: '', label: 'Выбери обнаруженный Caddy' }, ...proxies.map(p => ({ value: p.id, label: p.container || p.service || p.id }))],
      hint: target?.caddy_mode === 'docker' ? 'Собственный Caddy подключится через существующий механизм Nodekit. Он может кратковременно перезапуститься.' : undefined },
    ...(values.mode === 'basic_auth' ? [
      { name: 'username', label: 'Дополнительный логин Caddy', required: true, maxLength: 64, pattern: '[a-zA-Z0-9_.@-]+' },
      { name: 'password', label: previous?.password_hash ? 'Новый пароль (пусто — сохранить текущий)' : 'Пароль', type: 'password' as const,
        required: !previous?.password_hash, maxLength: 72,
        hint: 'От 8 символов, максимум 72 байта UTF-8. Хешируется в браузере; исходный пароль не отправляется в Nodekit и не сохраняется в YAML.' },
    ] : []),
    ...(values.mode === 'ip_allowlist' ? [
      { name: 'allowed_ips', label: 'Разрешённые IPv4 / IPv6 / CIDR', type: 'textarea' as const, required: true,
        hint: 'По одному адресу или сети на строку. Проверяется реальный адрес соединения с Caddy, а не присланный клиентом X-Forwarded-For.' },
    ] : []),
    { name: 'confirm', label: 'Сохранить настройки и открыть план применения', type: 'checkbox', required: true,
      hint: 'Панель и Xray перезапустятся. Обычный вход в 3x-ui останется вторым шагом после проверки Caddy.' },
  ];
  async function submit() {
    setValidation('');
    const proxy = proxies.find(p => p.id === values.caddy_id);
    if (!target || !source.caddy?.enabled || !proxy || !values.confirm) {
      setValidation('Нужны параметры установки с Caddy, актуальное обнаружение и подтверждение.'); return;
    }
    setWorking(true);
    try {
      const access: PanelAccessConfig = { mode: values.mode as PanelAccessConfig['mode'] };
      if (access.mode === 'basic_auth') {
        const password = String(values.password);
        if (password && (password.length < 8 || new TextEncoder().encode(password).length > 72)) {
          setValidation('Пароль должен содержать от 8 символов и не превышать 72 байта UTF-8.'); return;
        }
        access.username = String(values.username);
        access.password_hash = password ? await (await import('bcryptjs')).hash(password, 12) : previous?.password_hash;
        if (!access.password_hash) { setValidation('Укажи пароль.'); return; }
      } else if (access.mode === 'ip_allowlist') access.allowed_ips = String(values.allowed_ips).split(/[\s,]+/).filter(Boolean);
      const data = readConfig(record.yaml);
      data.caddy = { ...data.caddy, panel_access: access, config_path: proxy.config_path, ...(proxy.service ? { service: proxy.service } : {}) };
      data.deployment = { ...target, caddy_mode: 'existing',
        caddy_id: proxy.installation === 'docker' && proxy.container ? 'docker:' + proxy.container : proxy.id,
        subscription_bind: proxy.installation === 'docker' && proxy.network_mode !== 'host' ? proxy.host_gateway || '' : '127.0.0.1' };
      await onSave(writeConfig(data), target.caddy_mode === 'existing' ? 'configure' : 'attach_caddy');
    } catch { setValidation('Не удалось подготовить настройки доступа. Проверь поля и повтори сохранение.'); }
    finally { setWorking(false); }
  }
  return <FormDialog title="Доступ к 3x-ui" description={record.name} fields={fields} values={values} busy={busy || working}
    error={error || validation} onClose={onClose} submit="Сохранить и посмотреть план" onSubmit={() => void submit()}
    onChange={(name, value) => { setValidation(''); setValues(v => ({ ...v, [name]: value, ...(name !== 'confirm' ? { confirm: false } : {}) })); }}>
    <p className="feature-hint">Используется существующий Caddy. Защита относится только к пути панели; подписки и XHTTP сохраняют свои маршруты. Внутренний порт панели привязывается к loopback или приватному gateway Caddy.</p>
    {values.mode === 'ip_allowlist' && <p className="report-warning">При смене внешнего IP вход будет закрыт до обновления списка. За CDN или дополнительным прокси Caddy видит адрес прокси; такой сценарий требует отдельной настройки доверенных прокси.</p>}
    <p className="feature-hint">Резервный SSH-вход остаётся доступен к приватному адресу, показанному в обзоре ноды. Для выхода из Basic Auth может понадобиться закрыть окно браузера; пароль можно сменить здесь.</p>
  </FormDialog>;
}

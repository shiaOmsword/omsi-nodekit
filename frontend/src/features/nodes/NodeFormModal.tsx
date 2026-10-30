import { useState } from 'react';
import type { NodeRecord, NodeSummary, SSHKey } from '../../types';
import { readConfig, writeConfig } from '../../app/config';
import { Button, CodeBlock, FormDialog, Modal } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function NodeFormModal({
  record,
  template,
  nodes,
  keys,
  busy,
  error,
  onClose,
  onSave,
  onCreateKey,
}: {
  record: NodeRecord | null;
  template: string;
  nodes: NodeSummary[];
  keys: SSHKey[];
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (yaml: string, expectedId?: string) => void;
  onCreateKey?: (name: string) => Promise<SSHKey | undefined>;
}) {
  const [keyOpen, setKeyOpen] = useState(false);
  const [keyName, setKeyName] = useState('');
  const [createdKey, setCreatedKey] = useState<SSHKey | null>(null);
  const original = readConfig(record?.yaml || template);
  let index = 1;
  while (nodes.some((n) => n.id === 'node-' + index)) index++;
  const [values, setValues] = useState<FormValues>({
    id: record?.id || 'node-' + index,
    name: record?.name || '',
    host: record ? original.ssh.host : '',
    user: original.ssh.user || 'root',
    port: String(original.ssh.port || 22),
    key: original.ssh.key_id || '',
    identity: original.ssh.identity_file || '~/.ssh/id_ed25519',
    known_hosts: original.ssh.known_hosts_file || '~/.ssh/known_hosts',
    sudo: !!original.ssh.sudo,
    sudo_source: original.ssh.sudo_password_env
      ? 'env'
      : original.ssh.sudo_password
        ? 'password'
        : 'none',
    sudo_password: original.ssh.sudo_password || '',
    sudo_env: original.ssh.sudo_password_env || '',
    installation: record ? original.panel?.installation || 'auto' : 'auto',
  });
  const fields: FormField[] = [
    {
      name: 'name',
      label: 'Название ноды',
      required: true,
      maxLength: 80,
      placeholder: 'Например, Amsterdam · exit',
    },
    {
      name: 'id',
      label: 'ID ноды',
      required: true,
      disabled: !!record,
      pattern: '[a-z][a-z0-9-]{0,39}',
      hint: 'Латинские буквы, цифры и дефис.',
    },
    { name: 'host', label: 'Адрес сервера', required: true, placeholder: 'IP-адрес или домен' },
    { name: 'port', label: 'SSH-порт', type: 'number', required: true, min: 1, max: 65535 },
    { name: 'user', label: 'SSH-пользователь', required: true, placeholder: 'root или omsi' },
    {
      name: 'key',
      label: 'SSH-ключ',
      type: 'select',
      options: [
        { value: '', label: 'Файл на этом компьютере' },
        ...keys.map((k) => ({ value: k.id, label: k.name })),
        ...(values.key && !keys.some((k) => k.id === values.key)
          ? [{ value: String(values.key), label: 'Ключ недоступен — выбери другой' }]
          : []),
      ],
    },
    ...(!values.key
      ? [
          {
            name: 'identity',
            label: 'Путь к приватному ключу',
            required: true,
            placeholder: '~/.ssh/id_ed25519',
          } as FormField,
        ]
      : []),
    {
      name: 'known_hosts',
      label: 'Файл known_hosts',
      required: true,
      hint: 'Проверка ключа сервера остаётся включённой.',
    },
    {
      name: 'installation',
      label: 'Режим подключения к 3x-ui',
      type: 'select',
      options: [
        { value: 'auto', label: 'Определить существующую установку' },
        { value: 'native', label: 'Существующая 3x-ui в системе' },
        { value: 'docker', label: 'Существующая 3x-ui в Docker' },
        { value: 'managed', label: 'Новая / под управлением Nodekit' },
      ],
    },
    {
      name: 'sudo',
      label: 'Использовать sudo',
      type: 'checkbox',
      hint: 'Для SSH-пользователя, которому нужны права администратора.',
    },
    ...(values.sudo
      ? [
          {
            name: 'sudo_source',
            label: 'Пароль sudo',
            type: 'select',
            options: [
              { value: 'none', label: 'Не требуется (NOPASSWD)' },
              { value: 'password', label: 'Указать пароль' },
              { value: 'env', label: 'Взять из переменной окружения' },
            ],
          } as FormField,
        ]
      : []),
    ...(values.sudo && values.sudo_source === 'password'
      ? [
          {
            name: 'sudo_password',
            label: 'Пароль для sudo',
            type: 'password',
            required: true,
            hint: 'Сохраняется в локальной конфигурации ноды.',
          } as FormField,
        ]
      : []),
    ...(values.sudo && values.sudo_source === 'env'
      ? [
          {
            name: 'sudo_env',
            label: 'Имя переменной окружения',
            required: true,
            placeholder: 'NODE_SUDO_PASSWORD',
          } as FormField,
        ]
      : []),
  ];
  function submit() {
    const data = readConfig(record?.yaml || template);
    data.id = String(values.id);
    data.name = String(values.name).trim();
    data.ssh = {
      ...data.ssh,
      host: String(values.host).trim(),
      user: String(values.user).trim(),
      port: Number(values.port),
      key_id: values.key ? String(values.key) : null,
      identity_file: String(values.identity),
      known_hosts_file: String(values.known_hosts),
      sudo: !!values.sudo,
    };
    delete data.ssh.sudo_password;
    delete data.ssh.sudo_password_env;
    if (values.sudo && values.sudo_source === 'password')
      data.ssh.sudo_password = String(values.sudo_password);
    if (values.sudo && values.sudo_source === 'env')
      data.ssh.sudo_password_env = String(values.sudo_env);
    data.panel = { ...data.panel, installation: values.installation as 'auto' };
    onSave(writeConfig(data), record?.id);
  }
  return (
    <>
      <FormDialog
        title={record ? 'Настройки ноды' : 'Добавить ноду'}
        description="Подключение к серверу по SSH. Параметры 3x-ui можно заполнить после обнаружения."
        fields={fields}
        values={values}
        onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
        onSubmit={submit}
        onClose={onClose}
        busy={busy}
        error={error}
        submit={record ? 'Сохранить настройки' : 'Добавить ноду'}
      >
        {onCreateKey && (
          <div className="inline-key-create">
            <Button
              variant="text"
              onClick={() => {
                setCreatedKey(null);
                setKeyOpen(true);
              }}
            >
              Создать SSH-ключ здесь
            </Button>
            <span className="muted">Заполненные поля ноды сохранятся.</span>
          </div>
        )}
      </FormDialog>
      {keyOpen &&
        (createdKey ? (
          <Modal
            title="SSH-ключ создан"
            description="Добавь публичную часть на сервер. Новый ключ уже выбран в форме ноды."
            onClose={() => setKeyOpen(false)}
            footer={
              <Button variant="primary" onClick={() => setKeyOpen(false)}>
                Вернуться к ноде
              </Button>
            }
          >
            <CodeBlock value={createdKey.public_key} label="Публичный ключ" />
          </Modal>
        ) : (
          <FormDialog
            title="Создать SSH-ключ"
            description="Ed25519 без парольной фразы. Приватная часть хранится локально."
            fields={[{ name: 'name', label: 'Название ключа', required: true, maxLength: 80 }]}
            values={{ name: keyName }}
            onChange={(_, value) => setKeyName(String(value))}
            onSubmit={async () => {
              const key = await onCreateKey?.(keyName);
              if (key) {
                setValues((v) => ({ ...v, key: key.id }));
                setCreatedKey(key);
              }
            }}
            onClose={() => setKeyOpen(false)}
            busy={busy}
            error={error}
            submit="Создать ключ"
          />
        ))}
    </>
  );
}

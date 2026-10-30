import { ApiError, getErrorMessage } from '../../framework/api';

/** Explain node YAML errors using only the safe field/type metadata returned by the API. */
export function getNodeErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return getErrorMessage(error);

  const passwordError = error.details.find(detail => detail.field === 'ssh.sudo_password');
  if (!passwordError) return getErrorMessage(error);

  switch (passwordError.code) {
    case 'extra_forbidden':
      return 'Этот backend не поддерживает ssh.sudo_password. Обнови локальный backend до ветки dev и перезапусти процесс на порту 8765.';
    case 'string_type':
      return "ssh.sudo_password должен быть строкой: заключи пароль в одинарные кавычки YAML (sudo_password: 'пример').";
    case 'value_error':
      return 'ssh.sudo_password должен содержать от 1 до 4096 символов без переводов строки и NUL.';
    default:
      return getErrorMessage(error);
  }
}

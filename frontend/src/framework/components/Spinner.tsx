import { LoaderCircle } from 'lucide-react';
export function Spinner({ size = 16 }: { size?: number }) {
  return <LoaderCircle size={size} className="spin" aria-hidden="true" />;
}

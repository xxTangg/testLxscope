import { CredentialDialog } from './CredentialDialog';
import type { CredentialView } from '@/api';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	credential: CredentialView;
	onUpdated?: () => void;
}

export function EditCredentialDialog({ onUpdated, ...props }: Props) {
	return <CredentialDialog mode="edit" {...props} onSaved={onUpdated} />;
}

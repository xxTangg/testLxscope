import { CredentialDialog } from './CredentialDialog';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onCreated?: (credentialId: string) => void;
	defaultType?: string;
}

export function CreateCredentialDialog({ onCreated, ...props }: Props) {
	return <CredentialDialog mode="create" {...props} onSaved={onCreated} />;
}

import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';

import type { CredentialSchema } from '@/api';
import { Button } from '@/components/ui/button';
import { DialogFooter } from '@/components/ui/dialog';
import { useTranslation } from '@/i18n/useI18n';

export type FormProps = {
	schema: CredentialSchema;
	onSave: (
		data: Record<string, unknown>,
		verifications?: Record<string, string>,
	) => Promise<void>;
	onClose: () => void;
	submitting: boolean;
};

export function CredentialFormLayout({
	children,
	onClose,
	onSubmit,
	canSave,
	submitting,
}: Pick<FormProps, 'onClose' | 'submitting'> & {
	children: ReactNode;
	onSubmit: () => Promise<void>;
	canSave: boolean;
}) {
	const { t } = useTranslation();
	return (
		<form
			className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto]"
			autoComplete="off"
			onSubmit={(event) => {
				event.preventDefault();
				if (canSave && !submitting) void onSubmit();
			}}
		>
			<div className="min-h-0 overflow-y-auto px-5 pt-1 pb-4 sm:px-6">{children}</div>
			<DialogFooter className="m-0 flex-row flex-wrap justify-end bg-background px-5 py-3 sm:px-6">
				<Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>
					{t('common.cancel')}
				</Button>
				<Button type="submit" disabled={!canSave || submitting}>
					{submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
					{t(submitting ? 'common.saving' : 'credential.form.save')}
				</Button>
			</DialogFooter>
		</form>
	);
}

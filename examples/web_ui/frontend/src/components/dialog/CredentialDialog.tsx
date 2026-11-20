import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { CredentialFormLayout, type FormProps } from './CredentialFormLayout';
import { GatewayCredentialForm } from './GatewayCredentialForm';
import { credentialApi } from '@/api';
import type { CredentialView } from '@/api';
import { LONGXIN_AI_LABEL, NEW_API_CREDENTIAL_TYPE } from '@/api/credential';
import { SchemaForm, type SchemaFormValue } from '@/components/form/SchemaForm';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { useCredentials } from '@/hooks/useCredentials';
import { useTranslation } from '@/i18n/useI18n';

type CredentialFormProps = {
	onSaved?: (credentialId: string) => void;
} & ({ mode: 'create'; credential?: never } | { mode: 'edit'; credential: CredentialView });

type Props = CredentialFormProps & {
	open: boolean;
	onOpenChange: (open: boolean) => void;
};

const CREDENTIAL_SCHEMA_SKIP_FIELDS = new Set(['id', 'type', 'enabled']);

export function CredentialDialog({ open, onOpenChange, ...form }: Props) {
	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			{open && (
				<CredentialDialogContent
					key={form.credential?.id ?? NEW_API_CREDENTIAL_TYPE}
					{...form}
					onClose={() => onOpenChange(false)}
				/>
			)}
		</Dialog>
	);
}

function CredentialDialogContent({
	mode,
	credential,
	onSaved,
	onClose,
}: CredentialFormProps & { onClose: () => void }) {
	const { t } = useTranslation();
	const { create, update } = useCredentials();
	const [submitting, setSubmitting] = useState(false);
	const type = mode === 'edit' ? credential.data.type : NEW_API_CREDENTIAL_TYPE;
	const isGateway = type === NEW_API_CREDENTIAL_TYPE;
	const schemas = useQuery({
		queryKey: ['credential-schemas'],
		queryFn: credentialApi.schemas,
		retry: false,
	});
	const schema = schemas.data?.schemas.find((entry) => entry.properties.type?.const === type);

	const save: FormProps['onSave'] = async (data, model_verifications) => {
		setSubmitting(true);
		try {
			const body = { data, model_verifications };
			const id =
				mode === 'edit'
					? (await update(credential.id, body)).id
					: (await create(body)).credential_id;
			onClose();
			onSaved?.(id);
		} finally {
			setSubmitting(false);
		}
	};

	const preventCloseWhileSaving = (event: Event) => {
		if (submitting) event.preventDefault();
	};

	return (
		<DialogContent
			className="max-h-[calc(100vh-2rem)] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden rounded-[19px] p-0 supports-[height:100dvh]:max-h-[calc(100dvh-2rem)] sm:max-w-[520px]"
			showCloseButton={false}
			onEscapeKeyDown={preventCloseWhileSaving}
			onInteractOutside={preventCloseWhileSaving}
		>
			<DialogHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
				<DialogTitle className="text-xl leading-normal">
					{t(
						mode === 'edit'
							? 'dialog-credential-edit.title'
							: 'dialog-credential-create.title',
					)}
				</DialogTitle>
				<DialogDescription>
					{isGateway
						? LONGXIN_AI_LABEL
						: t('dialog-credential-edit.namedDescription', {
								name: credential?.data.name || credential?.id,
							})}
				</DialogDescription>
			</DialogHeader>
			{schema ? (
				isGateway ? (
					<GatewayCredentialForm
						schema={schema}
						credential={credential}
						onSave={save}
						onClose={onClose}
						submitting={submitting}
					/>
				) : (
					<SchemaCredentialForm
						schema={schema}
						credential={credential!}
						onSave={save}
						onClose={onClose}
						submitting={submitting}
					/>
				)
			) : (
				<div className="space-y-3 px-5 pb-5 sm:px-6">
					<p role="status" className="text-muted-foreground">
						{t(
							schemas.isPending
								? 'common.loading'
								: 'credential.form.schemaUnavailable',
						)}
					</p>
					<div className="flex flex-wrap justify-end gap-2">
						<Button variant="ghost" onClick={onClose}>
							{t('common.cancel')}
						</Button>
						{schemas.isError && (
							<Button
								variant="outline"
								onClick={() => void schemas.refetch()}
								disabled={schemas.isFetching}
							>
								{t('kbEmbedding.retry')}
							</Button>
						)}
					</div>
				</div>
			)}
		</DialogContent>
	);
}

function SchemaCredentialForm({
	schema,
	credential,
	onSave,
	...layout
}: FormProps & { credential: CredentialView }) {
	const { t } = useTranslation();
	const [draft, setDraft] = useState<Record<string, SchemaFormValue>>({});
	const values = { ...draft };
	for (const [name, prop] of Object.entries(schema.properties)) {
		if (!prop.writeOnly && !Object.hasOwn(draft, name)) {
			values[name] = credential.data[name] as SchemaFormValue;
		}
	}

	const submit = async () => {
		const data = { ...credential.data };
		for (const [key, value] of Object.entries(draft)) {
			if (value !== undefined && value !== '') data[key] = value;
		}
		try {
			await onSave(data);
		} catch {
			// The API client reports the error and the form stays open.
		}
	};

	return (
		<CredentialFormLayout {...layout} canSave onSubmit={submit}>
			<SchemaForm
				schema={schema}
				values={values}
				skipFields={CREDENTIAL_SCHEMA_SKIP_FIELDS}
				labelFor={(key, prop) =>
					t('credentialFieldLabels.' + key, {
						defaultValue: prop.title ?? key.replace(/_/g, ' '),
					})
				}
				helpFor={(key) => t('credentialFieldHelp.' + key, { defaultValue: '' })}
				onChange={(key, value) => setDraft((previous) => ({ ...previous, [key]: value }))}
			/>
		</CredentialFormLayout>
	);
}

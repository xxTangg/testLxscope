import { CircleAlert, Loader2, Plug, PlusCircle, Save } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { credentialApi } from '@/api';
import type { CredentialSchema, CredentialView } from '@/api';
import { ApiError } from '@/api/client';
import { NEW_API_CREDENTIAL_TYPE, type GatewayConnectionResult } from '@/api/credential';
import { DiagnosticReference } from '@/components/DiagnosticReference';
import { SchemaForm, type SchemaFormValue } from '@/components/form/SchemaForm';
import { Button } from '@/components/ui/button';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { useCredentials } from '@/hooks/useCredentials';
import { useTranslation } from '@/i18n/useI18n';

type CredentialFormProps = {
	onSaved?: (credentialId: string) => void;
} & (
	| { mode: 'create'; credential?: never; defaultType?: string }
	| { mode: 'edit'; credential: CredentialView; defaultType?: never }
);

type Props = CredentialFormProps & {
	open: boolean;
	onOpenChange: (open: boolean) => void;
};

const CREDENTIAL_SCHEMA_SKIP_FIELDS = new Set(['id', 'type', 'enabled']);
const NEW_API_SCHEMA_SKIP_FIELDS = new Set([...CREDENTIAL_SCHEMA_SKIP_FIELDS, 'embedding_models']);

type ConnectionCheck =
	| GatewayConnectionResult
	| { status: 'checking' }
	| { status: 'error'; code: 'invalid_address' | 'check_unavailable' };

export function CredentialDialog({ open, onOpenChange, ...form }: Props) {
	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			{open && (
				<CredentialDialogContent
					key={form.credential?.id ?? form.defaultType}
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
	defaultType,
	onSaved,
	onClose,
}: CredentialFormProps & { onClose: () => void }) {
	const { create, update } = useCredentials();
	const { t } = useTranslation();
	const [schemas, setSchemas] = useState<CredentialSchema[]>();
	const [selectedType, setSelectedType] = useState<string>();
	const [draft, setDraft] = useState<Record<string, SchemaFormValue>>({});
	const [savedData] = useState(mode === 'edit' ? credential?.data : undefined);
	const [submitting, setSubmitting] = useState(false);
	const [connectionCheck, setConnectionCheck] = useState<ConnectionCheck | null>(null);
	const checkController = useRef<AbortController | null>(null);

	useEffect(() => {
		let active = true;
		credentialApi.schemas().then(
			({ schemas }) => {
				if (active) setSchemas(schemas);
			},
			() => {
				if (active) setSchemas([]);
			},
		);
		return () => {
			active = false;
			checkController.current?.abort();
		};
	}, []);

	const loading = schemas === undefined;
	const editing = mode === 'edit';
	const messages = editing ? 'dialog-credential-edit' : 'dialog-credential-create';
	const savedType = savedData?.type as string | undefined;
	const createSchemas = schemas?.filter(
		(entry) => entry.properties.type?.const === NEW_API_CREDENTIAL_TYPE,
	);
	const firstType = createSchemas?.[0]?.properties.type?.const as string | undefined;
	const type = editing ? savedType : (selectedType ?? defaultType ?? firstType);
	const schema = schemas?.find((entry) => entry.properties.type?.const === type);
	const fields = Object.entries(schema?.properties ?? {}).filter(
		([key, prop]) => key !== 'id' && key !== 'type' && prop.const === undefined,
	);
	const values = { ...draft };
	for (const [key, prop] of fields) {
		if (prop.writeOnly || key === 'embedding_models' || Object.hasOwn(draft, key)) continue;
		const value = savedData?.[key] ?? (editing ? undefined : prop.default);
		if (value !== undefined) values[key] = value as SchemaFormValue;
	}

	const isNewApi = type === NEW_API_CREDENTIAL_TYPE;
	const baseUrl = String(values.base_url ?? '').trim();
	const apiKey = String(values.api_key ?? '').trim();
	const chatModels = String(values.models ?? '');
	const savedUrl = String(savedData?.base_url ?? '');
	const canReuseKey = Boolean(savedUrl && baseUrl.replace(/\/+$/, '') === savedUrl);
	const canSave = !isNewApi || Boolean(baseUrl && (apiKey || canReuseKey));
	const connectionChanged = Boolean(
		editing && isNewApi && (baseUrl.replace(/\/+$/, '') !== savedUrl || apiKey),
	);

	const setField = (key: string, value: SchemaFormValue) => {
		if (isNewApi && (key === 'base_url' || key === 'api_key')) {
			checkController.current?.abort();
			checkController.current = null;
			setConnectionCheck(null);
		}
		setDraft((previous) => {
			const current = previous[key] ?? (key === 'api_key' ? '' : values[key]) ?? '';
			const updated = { ...previous, [key]: value };
			const oldValue = String(current).trim();
			const newValue = String(value ?? '').trim();
			const changed =
				key === 'base_url'
					? oldValue.replace(/\/+$/, '') !== newValue.replace(/\/+$/, '')
					: oldValue !== newValue;
			if (isNewApi && (key === 'base_url' || key === 'api_key') && changed) {
				updated.models = '';
			}
			return updated;
		});
	};

	const changeType = (nextType: string) => {
		setSelectedType(nextType);
		setDraft({});
	};

	const testConnection = async () => {
		if (!canSave || checkController.current) return;
		const controller = new AbortController();
		checkController.current = controller;
		setConnectionCheck({ status: 'checking' });
		try {
			const result = await credentialApi.checkConnection(
				{
					base_url: baseUrl,
					api_key: apiKey || undefined,
					credential_id: !apiKey && canReuseKey ? credential?.id : undefined,
				},
				controller.signal,
			);
			if (!controller.signal.aborted) setConnectionCheck(result);
		} catch (error) {
			if (!controller.signal.aborted) {
				setConnectionCheck({
					status: 'error',
					code:
						error instanceof ApiError && error.status === 422
							? 'invalid_address'
							: 'check_unavailable',
				});
			}
		} finally {
			if (checkController.current === controller) checkController.current = null;
		}
	};

	const submit = async () => {
		if (!schema || !canSave || submitting) return;
		const data: Record<string, unknown> = { ...savedData, type };
		for (const [key] of fields) {
			const value = values[key];
			if (value !== undefined && value !== '') data[key] = value;
		}
		if (isNewApi) {
			data.models = chatModels;
			if (apiKey) data.api_key = apiKey;
			else delete data.api_key;
		}

		setSubmitting(true);
		try {
			const id =
				editing && credential
					? (await update(credential.id, { data, models_confirmed: connectionChanged }))
							.id
					: (await create({ data })).credential_id;
			onClose();
			onSaved?.(id);
		} catch {
			// The API client displays the error and the draft stays open.
		} finally {
			setSubmitting(false);
		}
	};

	const SubmitIcon = editing ? Save : PlusCircle;

	return (
		<DialogContent className="max-h-[calc(100vh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] supports-[height:100dvh]:max-h-[calc(100dvh-2rem)] sm:max-w-[520px]">
			<DialogHeader>
				<DialogTitle>{t(messages + '.title')}</DialogTitle>
				<DialogDescription>
					{editing
						? t('dialog-credential-edit.namedDescription', {
								name: savedData?.name || credential?.id,
							})
						: t('dialog-credential-create.description')}
				</DialogDescription>
			</DialogHeader>
			<FieldGroup className="min-h-0 overflow-y-auto px-1">
				{!editing && (
					<Field>
						<FieldLabel>{t('dialog-credential-create.selectType')}</FieldLabel>
						<Select value={type ?? ''} onValueChange={changeType} disabled={loading}>
							<SelectTrigger>
								<SelectValue
									placeholder={
										loading
											? t('common.loading')
											: t('dialog-credential-create.selectTypePlaceholder')
									}
								/>
							</SelectTrigger>
							<SelectContent>
								{createSchemas?.map((entry) => {
									const provider = entry.properties.type?.const as string;
									return (
										<SelectItem key={provider} value={provider}>
											{entry.title}
										</SelectItem>
									);
								})}
							</SelectContent>
						</Select>
					</Field>
				)}
				{editing && loading && (
					<p className="text-sm text-muted-foreground">{t('common.loading')}</p>
				)}
				{schema && (
					<SchemaForm
						schema={schema}
						values={values}
						labelFor={(key, prop) =>
							t('credentialFieldLabels.' + key, {
								defaultValue: prop.title ?? key.replace(/_/g, ' '),
							})
						}
						skipFields={
							isNewApi ? NEW_API_SCHEMA_SKIP_FIELDS : CREDENTIAL_SCHEMA_SKIP_FIELDS
						}
						placeholderFor={(key) =>
							key === 'models' && isNewApi
								? t('newApiModels.chatPlaceholder')
								: key === 'api_key' && isNewApi && canReuseKey
									? t('newApiModels.keepKey')
									: undefined
						}
						descriptionFor={(key) =>
							key === 'models' && isNewApi
								? t('newApiModels.chatOptional')
								: undefined
						}
						helpFor={(key) => t('credentialFieldHelp.' + key, { defaultValue: '' })}
						renderAfterField={(key) =>
							key === 'base_url' &&
							isNewApi && (
								<div className="flex flex-col items-start gap-1.5">
									<Button
										type="button"
										variant="outline"
										size="sm"
										disabled={
											!canSave || submitting || connectionCheck?.status === 'checking'
										}
										onClick={testConnection}
									>
										{connectionCheck?.status === 'checking' ? (
											<Loader2 className="animate-spin" />
										) : (
											<Plug />
										)}
										{t(
											connectionCheck?.status === 'checking'
												? 'credential.connectionCheck.checking'
												: 'credential.connectionCheck.button',
										)}
									</Button>
									{connectionCheck?.status === 'passed' && (
										<p className="text-sm" role="status">
											{t('credential.connectionCheck.passed', {
												ms: connectionCheck.elapsed_ms,
											})}
										</p>
									)}
									{(connectionCheck?.status === 'failed' ||
										connectionCheck?.status === 'error') && (
										<p className="text-sm text-destructive" role="status">
											{t(`credential.connectionCheck.errors.${connectionCheck.code}`, {
												status:
													connectionCheck.status === 'failed'
														? connectionCheck.http_status
														: undefined,
											})}
										</p>
									)}
									{connectionCheck?.status === 'failed' && (
										<DiagnosticReference
											key={connectionCheck.diagnostic_id}
											id={connectionCheck.diagnostic_id}
										/>
									)}
								</div>
							)
						}
						onChange={setField}
					/>
				)}
				{schema && isNewApi && connectionChanged && (
					<p role="status" className="text-xs text-muted-foreground">
						{t('credential.connectionChanged')}
					</p>
				)}
			</FieldGroup>
			<DialogFooter>
				<Button variant="ghost" onClick={onClose} disabled={submitting}>
					<CircleAlert className="size-3.5" />
					{t('common.cancel')}
				</Button>
				<Button onClick={submit} disabled={submitting || loading || !schema || !canSave}>
					{submitting ? (
						<Loader2 className="size-3.5 animate-spin" />
					) : (
						<SubmitIcon className="size-3.5" />
					)}
					{editing
						? t(submitting ? 'common.saving' : 'common.save')
						: t(submitting ? 'common.creating' : 'common.create')}
				</Button>
			</DialogFooter>
		</DialogContent>
	);
}

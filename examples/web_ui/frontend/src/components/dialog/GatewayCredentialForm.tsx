import { Loader2, Plus, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';

import { CredentialFormLayout, type FormProps } from './CredentialFormLayout';
import type { CredentialView } from '@/api';
import { ApiError } from '@/api/client';
import { credentialApi, NEW_API_CREDENTIAL_TYPE, type ModelCheckResult } from '@/api/credential';
import { DiagnosticReference } from '@/components/DiagnosticReference';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Field,
	FieldDescription,
	FieldGroup,
	FieldLabel,
	FieldLegend,
	FieldSet,
} from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

type ModelRow = { id: number; value: string };
type ModelCheck = ModelCheckResult | { status: 'checking' };

const MODEL_SEPARATOR = /[\r\n,，]/;

function isGatewayAddress(value: string) {
	try {
		const url = new URL(value);
		return (
			/^https?:\/\//i.test(value) &&
			url.hostname &&
			url.port !== '0' &&
			!url.username &&
			!url.password &&
			!/[?#]/.test(value)
		);
	} catch {
		return false;
	}
}

export function GatewayCredentialForm({
	schema,
	credential,
	onSave,
	onClose,
	submitting,
}: FormProps & { credential?: CredentialView }) {
	const { t } = useTranslation();
	const fieldId = useId();
	const saved = credential?.data;
	const savedUrl = String(saved?.base_url ?? '');
	const savedModels = [
		...new Set(
			String(saved?.models ?? '')
				.split(MODEL_SEPARATOR)
				.map((id) => id.trim())
				.filter(Boolean),
		),
	];
	const [name, setName] = useState(String(saved?.name ?? ''));
	const [address, setAddress] = useState(
		savedUrl || String(schema.properties.base_url?.default ?? ''),
	);
	const [key, setKey] = useState('');
	const [showKey, setShowKey] = useState(false);
	const [models, setModels] = useState<ModelRow[]>(() =>
		(savedModels.length ? savedModels : ['']).map((value, id) => ({ id, value })),
	);
	const nextId = useRef(models.length);
	const [checks, setChecks] = useState<Record<number, ModelCheck>>({});
	const [checking, setChecking] = useState(false);
	const controllerRef = useRef<AbortController | null>(null);

	useEffect(() => () => controllerRef.current?.abort(), []);

	const baseUrl = address.trim().replace(/\/+$/, '');
	const apiKey = key.trim();
	const addressValid = Boolean(isGatewayAddress(baseUrl));
	const sameAddress = Boolean(savedUrl && baseUrl === savedUrl.replace(/\/+$/, ''));
	const canReuseKey = sameAddress && credential?.enabled !== false;
	const modelIds = models.map((model) => model.value.trim());
	const invalidModel = modelIds.some((value) => MODEL_SEPARATOR.test(value));
	const duplicates = new Set(modelIds.filter(Boolean)).size !== modelIds.filter(Boolean).length;
	const validModels =
		modelIds.length > 0 && modelIds.every(Boolean) && !invalidModel && !duplicates;
	const unchanged =
		sameAddress &&
		!apiKey &&
		savedModels.length === models.length &&
		modelIds.every((value, index) => value === savedModels[index]);
	const allPassed = models.every(({ id }) => {
		const check = checks[id];
		return check?.status === 'passed' && Boolean(check.verification);
	});
	const hasFailure = models.some(({ id }) => checks[id]?.status === 'failed');
	const canTest = addressValid && validModels && (Boolean(apiKey) || canReuseKey);
	const canSave =
		addressValid && validModels && !checking && (allPassed || (unchanged && !hasFailure));
	const keyRequired = !canReuseKey && !unchanged;
	const formStatus =
		[
			[invalidModel, 'onePerRow'],
			[duplicates, 'duplicate'],
			[checking, 'testingHint'],
			[hasFailure, 'testFailed'],
			[allPassed, 'testPassed'],
			[unchanged, 'retestOnChange'],
			[sameAddress && !canReuseKey && !apiKey, 'disabledKeyHint'],
		].find(([applies]) => applies)?.[1] ?? 'testRequired';

	const clearTests = () => {
		controllerRef.current?.abort();
		controllerRef.current = null;
		setChecks({});
		setChecking(false);
	};

	const addModel = () => {
		clearTests();
		const id = nextId.current++;
		setModels((previous) => [...previous, { id, value: '' }]);
		requestAnimationFrame(() => document.getElementById(`${fieldId}-model-${id}`)?.focus());
	};

	const testModels = async () => {
		if (!canTest || controllerRef.current) return;
		const controller = new AbortController();
		controllerRef.current = controller;
		setChecking(true);
		setChecks(Object.fromEntries(models.map(({ id }) => [id, { status: 'checking' }])));
		const settings = {
			base_url: baseUrl,
			api_key: apiKey || undefined,
			credential_id: credential?.id,
		};
		let next = 0;
		try {
			// Keep per-model progress visible without sending all requests at once.
			await Promise.all(
				Array.from({ length: Math.min(3, models.length) }, async () => {
					while (!controller.signal.aborted && next < models.length) {
						const index = next++;
						const { id } = models[index];
						const model = modelIds[index];
						let check: ModelCheckResult;
						try {
							check = await credentialApi.checkDraftModel(
								{ ...settings, model },
								controller.signal,
							);
						} catch (error) {
							check = {
								model,
								status: 'failed',
								detail: error instanceof ApiError ? error.message : '',
							};
						}
						if (!controller.signal.aborted) {
							setChecks((previous) => ({ ...previous, [id]: check }));
						}
					}
				}),
			);
		} finally {
			if (controllerRef.current === controller) {
				controllerRef.current = null;
				setChecking(false);
			}
		}
	};

	const submit = async () => {
		const data = {
			...saved,
			type: NEW_API_CREDENTIAL_TYPE,
			name: name.trim(),
			base_url: baseUrl,
			models: modelIds.join('\n'),
			api_key: apiKey || undefined,
		};
		const verifications = Object.fromEntries(
			models.flatMap(({ id }, index) => {
				const check = checks[id];
				return check?.status === 'passed' && check.verification
					? [[modelIds[index], check.verification]]
					: [];
			}),
		);
		try {
			await onSave(data, verifications);
		} catch (error) {
			// An expired check must be repeated against the same draft.
			if (error instanceof ApiError && error.status === 409) clearTests();
		}
	};

	return (
		<CredentialFormLayout
			onClose={onClose}
			onSubmit={submit}
			canSave={canSave}
			submitting={submitting}
		>
			<FieldGroup className="gap-3.5">
				<Field className="gap-1.5">
					<FieldLabel htmlFor={fieldId + '-name'}>
						{t('credential.form.name')}
						<span className="text-xs font-normal text-muted-foreground">
							{t('credential.form.optional')}
						</span>
					</FieldLabel>
					<Input
						id={fieldId + '-name'}
						value={name}
						placeholder={t('credential.form.namePlaceholder')}
						onChange={(event) => setName(event.target.value)}
						disabled={submitting}
						className="h-9"
					/>
				</Field>
				<Field className="gap-1.5">
					<FieldLabel htmlFor={fieldId + '-url'}>
						{t('credential.form.address')}
						<span aria-hidden="true" className="text-destructive">
							*
						</span>
					</FieldLabel>
					<Input
						id={fieldId + '-url'}
						type="url"
						required
						value={address}
						spellCheck={false}
						aria-invalid={Boolean(address.trim() && !addressValid)}
						aria-describedby={
							address.trim() && !addressValid ? fieldId + '-address-help' : undefined
						}
						onChange={(event) => {
							setAddress(event.target.value);
							clearTests();
						}}
						disabled={submitting}
						className="h-9"
					/>
					{address.trim() && !addressValid && (
						<p id={fieldId + '-address-help'} className="text-xs text-destructive">
							{t('credential.connectionCheck.errors.invalid_address')}
						</p>
					)}
				</Field>
				<Field className="gap-1.5">
					<FieldLabel htmlFor={fieldId + '-key'}>
						API Key
						{keyRequired && (
							<span aria-hidden="true" className="text-destructive">
								*
							</span>
						)}
					</FieldLabel>
					<div className="flex items-center gap-2">
						<Input
							id={fieldId + '-key'}
							type={showKey ? 'text' : 'password'}
							autoComplete="new-password"
							spellCheck={false}
							required={keyRequired}
							placeholder={
								sameAddress
									? t('credential.form.keepKey')
									: t('credential.form.keyPlaceholder')
							}
							value={key}
							onChange={(event) => {
								setKey(event.target.value);
								clearTests();
							}}
							disabled={submitting}
							className="h-9"
						/>
						<Button
							type="button"
							variant="outline"
							aria-controls={fieldId + '-key'}
							onClick={() => setShowKey((previous) => !previous)}
							disabled={submitting}
						>
							{t(showKey ? 'credential.form.hideKey' : 'credential.form.showKey')}
						</Button>
					</div>
				</Field>
				<FieldSet className="min-w-0 gap-2.5" aria-describedby={fieldId + '-model-help'}>
					<FieldLegend variant="label">
						{t('credential.form.models')}{' '}
						<span aria-hidden="true" className="text-destructive">
							*
						</span>
					</FieldLegend>
					<FieldDescription id={fieldId + '-model-help'} className="text-xs">
						{t('credential.form.modelHelp')}
					</FieldDescription>
					{models.map(({ id, value }, index) => {
						const check = checks[id];
						const rowInvalid =
							MODEL_SEPARATOR.test(value) ||
							(Boolean(modelIds[index]) &&
								modelIds.indexOf(modelIds[index]) !== index);
						return (
							<div key={id} className="space-y-1">
								<div className="flex min-w-0 items-center gap-1.5 sm:gap-2">
									<Input
										id={`${fieldId}-model-${id}`}
										value={value}
										required
										spellCheck={false}
										autoComplete="off"
										aria-invalid={rowInvalid || check?.status === 'failed'}
										aria-label={t('credential.form.modelLabel', {
											index: index + 1,
										})}
										placeholder={t('credential.form.modelPlaceholder')}
										onChange={(event) => {
											const value = event.target.value;
											setModels((previous) =>
												previous.map((row) =>
													row.id === id ? { id, value } : row,
												),
											);
											clearTests();
										}}
										disabled={submitting}
										className="h-9 min-w-0 font-mono placeholder:font-sans"
									/>
									<Badge
										variant="secondary"
										className={cn(
											'shrink-0',
											check?.status === 'passed' &&
												'text-emerald-700 dark:text-emerald-300',
											check?.status === 'failed' && 'text-destructive',
										)}
									>
										{t(
											check
												? `credential.check.${check.status}`
												: unchanged
													? 'credential.form.configured'
													: 'credential.check.unchecked',
										)}
									</Badge>
									{models.length > 1 && (
										<Button
											type="button"
											variant="ghost"
											size="icon-sm"
											className="shrink-0"
											aria-label={t('credential.form.removeModel', {
												index: index + 1,
											})}
											onClick={() => {
												setModels((previous) =>
													previous.filter((row) => row.id !== id),
												);
												clearTests();
											}}
											disabled={submitting}
										>
											<X aria-hidden="true" />
										</Button>
									)}
								</div>
								{check?.status === 'failed' && <ModelCheckFailure check={check} />}
							</div>
						);
					})}
					<div className="flex flex-wrap items-center justify-between gap-2">
						<Button
							type="button"
							variant="ghost"
							size="sm"
							onClick={addModel}
							disabled={submitting}
						>
							<Plus aria-hidden="true" />
							{t('credential.form.addModel')}
						</Button>
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={() => void testModels()}
							disabled={!canTest || checking || submitting}
							aria-describedby={fieldId + '-test-result'}
						>
							{checking && <Loader2 className="animate-spin" aria-hidden="true" />}
							{t(
								checking
									? 'credential.form.testing'
									: hasFailure || allPassed
										? 'credential.form.retest'
										: 'credential.form.test',
							)}
						</Button>
					</div>
					<p
						id={fieldId + '-test-result'}
						role="status"
						className={cn(
							'text-xs text-muted-foreground',
							(invalidModel || duplicates || hasFailure) && 'text-destructive',
						)}
					>
						{t('credential.form.' + formStatus)}
					</p>
				</FieldSet>
			</FieldGroup>
		</CredentialFormLayout>
	);
}

function ModelCheckFailure({ check }: { check: ModelCheckResult }) {
	const { t } = useTranslation();
	const fallback = check.detail || t('credential.form.checkUnavailable');
	const message =
		check.code === 'endpoint_not_found'
			? t('credential.form.modelNotFound')
			: check.code === 'invalid_response'
				? t('credential.form.invalidModelResponse')
				: check.code
					? t(`credential.connectionCheck.errors.${check.code}`, {
							status: check.http_status,
							defaultValue: fallback,
						})
					: fallback;
	return (
		<div className="space-y-1">
			<p className="text-xs text-destructive">{message}</p>
			{check.diagnostic_id && <DiagnosticReference id={check.diagnostic_id} />}
		</div>
	);
}

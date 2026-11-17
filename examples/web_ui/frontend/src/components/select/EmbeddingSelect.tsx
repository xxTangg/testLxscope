import { Loader2, PlusCircle, RefreshCw } from 'lucide-react';
import { useEffect, useId, useState } from 'react';

import { DimensionSelect } from './DimensionSelect';
import { knowledgeBaseApi } from '@/api';
import type { DimensionPolicy, EmbeddingModelConfig, KbEmbeddingProvider } from '@/api';
import { NEW_API_CREDENTIAL_TYPE } from '@/api/credential';
import { Button } from '@/components/ui/button';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { useTranslation } from '@/i18n/useI18n';
import { credentialLabel } from '@/utils/common';

interface Props {
	value: EmbeddingModelConfig | null;
	providers: KbEmbeddingProvider[];
	policy: DimensionPolicy | null;
	loading?: boolean;
	disabled?: boolean;
	onChange: (config: EmbeddingModelConfig | null) => void;
	onAddCredential?: () => void;
}

export function EmbeddingSelect({
	value,
	providers,
	policy,
	loading,
	disabled,
	onChange,
	onAddCredential,
}: Props) {
	const { t } = useTranslation();
	const fieldId = useId();
	const [selectedId, setSelectedId] = useState('');
	const credentialId =
		selectedId ||
		value?.credential_id ||
		(providers.length === 1 ? providers[0].credential.id : '');
	const provider = providers.find((entry) => entry.credential.id === credentialId);

	useEffect(() => {
		if (value && !providers.some((entry) => entry.credential.id === value.credential_id))
			onChange(null);
	}, [value, providers, onChange]);

	return (
		<div className="grid gap-4">
			<Field>
				<div className="flex items-center justify-between gap-2">
					<FieldLabel htmlFor={fieldId}>{t('kbEmbedding.credential')}</FieldLabel>
					{onAddCredential && (
						<Button
							type="button"
							size="sm"
							variant="ghost"
							disabled={disabled}
							onClick={onAddCredential}
						>
							<PlusCircle />
							{t('embedding-select.addCredential')}
						</Button>
					)}
				</div>
				<Select
					value={provider?.credential.id ?? ''}
					disabled={loading || disabled}
					onValueChange={(id) => {
						setSelectedId(id);
						onChange(null);
					}}
				>
					<SelectTrigger id={fieldId}>
						<SelectValue
							placeholder={
								loading ? t('common.loading') : t('kbEmbedding.selectCredential')
							}
						/>
					</SelectTrigger>
					<SelectContent>
						{providers.map(({ credential }) => (
							<SelectItem key={credential.id} value={credential.id}>
								{credentialLabel(credential)}
							</SelectItem>
						))}
					</SelectContent>
				</Select>
			</Field>
			{provider &&
				(provider.credential.data.type === NEW_API_CREDENTIAL_TYPE ? (
					<NewApiEmbeddingFields
						key={provider.credential.id}
						provider={provider}
						policy={policy}
						disabled={disabled}
						onChange={onChange}
					/>
				) : (
					<CatalogueEmbeddingFields
						provider={provider}
						value={value}
						disabled={disabled}
						onChange={onChange}
					/>
				))}
		</div>
	);
}

function CatalogueEmbeddingFields({
	provider,
	value,
	disabled,
	onChange,
}: {
	provider: KbEmbeddingProvider;
	value: EmbeddingModelConfig | null;
	disabled?: boolean;
	onChange: Props['onChange'];
}) {
	const { t } = useTranslation();
	const fieldId = useId();
	const card = provider.models.find((entry) => entry.name === value?.model);
	const dimensions = card?.supported_dimensions?.length
		? card.supported_dimensions
		: card
			? [card.dimensions]
			: null;
	return (
		<>
			<Field>
				<FieldLabel htmlFor={fieldId}>
					{t('dialog-knowledge-base-create.embeddingModel.label')}
				</FieldLabel>
				<Select
					value={card?.name ?? ''}
					disabled={disabled}
					onValueChange={(model) => {
						const selected = provider.models.find((entry) => entry.name === model);
						if (selected)
							onChange({
								type: String(provider.credential.data.type),
								credential_id: provider.credential.id,
								model,
								dimensions: selected.dimensions,
								parameters: {},
							});
					}}
				>
					<SelectTrigger id={fieldId}>
						<SelectValue placeholder={t('embedding-select.placeholder')} />
					</SelectTrigger>
					<SelectContent>
						{provider.models.map((entry) => (
							<SelectItem key={entry.name} value={entry.name}>
								{entry.label}
							</SelectItem>
						))}
					</SelectContent>
				</Select>
			</Field>
			{card && (
				<Field orientation="horizontal">
					<FieldLabel>{t('dialog-knowledge-base-create.dimension.label')}</FieldLabel>
					<DimensionSelect
						value={value?.dimensions}
						options={dimensions}
						disabled={disabled}
						onChange={(dimension) => {
							if (value) onChange({ ...value, dimensions: dimension });
						}}
					/>
				</Field>
			)}
		</>
	);
}

function NewApiEmbeddingFields({
	provider,
	policy,
	disabled,
	onChange,
}: {
	provider: KbEmbeddingProvider;
	policy: DimensionPolicy | null;
	disabled?: boolean;
	onChange: Props['onChange'];
}) {
	const { t } = useTranslation();
	const fieldId = useId();
	const credentialId = provider.credential.id;
	const [model, setModel] = useState('');
	const modelId = model.trim();
	const [candidates, setCandidates] = useState<string[]>([]);
	const [discoveryFailed, setDiscoveryFailed] = useState(false);
	const [attempt, setAttempt] = useState(0);
	const [manualDimensions, setManualDimensions] = useState('');
	const [result, setResult] = useState<{
		model: string;
		attempt: number;
		dimensions: number | null;
	}>();

	useEffect(() => {
		const controller = new AbortController();
		knowledgeBaseApi.discoverEmbeddingModels(credentialId, controller.signal).then(
			(models) => {
				if (!controller.signal.aborted) setCandidates(models.map((entry) => entry.id));
			},
			() => {
				if (!controller.signal.aborted) setDiscoveryFailed(true);
			},
		);
		return () => controller.abort();
	}, [credentialId]);

	useEffect(() => {
		if (!modelId) return;
		const controller = new AbortController();
		const timer = window.setTimeout(() => {
			knowledgeBaseApi
				.probeEmbeddingDimensions(credentialId, modelId, controller.signal)
				.then(
					({ dimensions }) => {
						if (!controller.signal.aborted)
							setResult({ model: modelId, attempt, dimensions });
					},
					() => {
						if (!controller.signal.aborted)
							setResult({ model: modelId, attempt, dimensions: null });
					},
				);
		}, 500);
		return () => {
			window.clearTimeout(timer);
			controller.abort();
		};
	}, [credentialId, modelId, attempt]);

	const current = result?.model === modelId && result?.attempt === attempt ? result : undefined;
	const failed = current?.dimensions === null;
	const dimensions = failed ? Number(manualDimensions) : current?.dimensions;
	const validDimensions =
		typeof dimensions === 'number' && Number.isSafeInteger(dimensions) && dimensions > 0;
	const compatible = !policy || policy.kind === 'any' || dimensions === policy.dimension;
	const ready = Boolean(modelId && validDimensions && compatible);

	useEffect(() => {
		onChange(
			ready
				? {
						type: NEW_API_CREDENTIAL_TYPE,
						credential_id: credentialId,
						model: modelId,
						dimensions: dimensions as number,
						parameters: {},
					}
				: null,
		);
	}, [ready, credentialId, modelId, dimensions, onChange]);

	const suggestions = [
		...new Set([...candidates, ...provider.models.map((entry) => entry.name)]),
	];

	return (
		<Field>
			<FieldLabel htmlFor={fieldId}>
				{t('dialog-knowledge-base-create.embeddingModel.label')}
			</FieldLabel>
			<Input
				id={fieldId}
				list={fieldId + '-models'}
				value={model}
				disabled={disabled}
				autoComplete="off"
				placeholder={t('kbEmbedding.selectModel')}
				onChange={(event) => {
					setModel(event.target.value);
					if (event.target.value.trim() !== modelId) {
						setManualDimensions('');
						onChange(null);
					}
				}}
			/>
			<datalist id={fieldId + '-models'}>
				{suggestions.map((id) => (
					<option key={id} value={id} />
				))}
			</datalist>
			{discoveryFailed && (
				<FieldDescription>{t('kbEmbedding.discoveryFailed')}</FieldDescription>
			)}
			{modelId && !current && (
				<p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
					<Loader2 className="size-3.5 animate-spin" />
					{t('kbEmbedding.detecting')}
				</p>
			)}
			{current?.dimensions && (
				<FieldDescription role="status">
					{t('kbEmbedding.detected', { dimensions: current.dimensions })}
				</FieldDescription>
			)}
			{failed && (
				<>
					<div className="flex items-center justify-between gap-2">
						<FieldDescription role="status">
							{t('kbEmbedding.detectFailed')}
						</FieldDescription>
						<Button
							type="button"
							size="sm"
							variant="ghost"
							disabled={disabled}
							onClick={() => {
								onChange(null);
								setManualDimensions('');
								setAttempt((value) => value + 1);
							}}
						>
							<RefreshCw />
							{t('kbEmbedding.retry')}
						</Button>
					</div>
					<details>
						<summary className="cursor-pointer text-xs text-muted-foreground">
							{t('kbEmbedding.advanced')}
						</summary>
						<Field className="mt-3">
							<FieldLabel htmlFor={fieldId + '-dimensions'}>
								{t('kbEmbedding.manualDimensions')}
							</FieldLabel>
							<Input
								id={fieldId + '-dimensions'}
								type="number"
								min={1}
								step={1}
								value={manualDimensions}
								disabled={disabled}
								onChange={(event) => setManualDimensions(event.target.value)}
							/>
							<FieldDescription>{t('kbEmbedding.manualHint')}</FieldDescription>
						</Field>
					</details>
				</>
			)}
			{validDimensions && !compatible && (
				<p role="alert" className="text-xs text-destructive">
					{t('kbEmbedding.incompatible', { dimensions: policy?.dimension })}
				</p>
			)}
		</Field>
	);
}

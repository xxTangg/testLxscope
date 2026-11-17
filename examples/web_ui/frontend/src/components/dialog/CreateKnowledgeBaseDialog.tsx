import { CircleAlert, Info, Loader2, PlusCircle } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import type { ChunkerConfig, ChunkerInfo, EmbeddingModelConfig, JSONSchema } from '@/api';
import {
	type SchemaFormValue,
	SchemaForm,
	defaultValuesFromSchema,
} from '@/components/form/SchemaForm';
import { ChunkerSelect } from '@/components/select/ChunkerSelect';
import { EmbeddingSelect } from '@/components/select/EmbeddingSelect';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert.tsx';
import { Button } from '@/components/ui/button.tsx';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog.tsx';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field.tsx';
import { Input } from '@/components/ui/input.tsx';
import { Separator } from '@/components/ui/separator.tsx';
import { Textarea } from '@/components/ui/textarea.tsx';
import { useChunkers } from '@/hooks/useChunkers';
import { useKbEmbeddingModels } from '@/hooks/useKbEmbeddingModels';
import { useKnowledgeBases } from '@/hooks/useKnowledgeBases';
import { useTranslation } from '@/i18n/useI18n.ts';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onCreated?: (knowledgeBaseId: string) => void;
	onAddCredential?: () => void;
	/**
	 * Bumped externally (e.g. after a credential is created) to ask the
	 * embedding selector to refetch its options.
	 */
	credentialRefetchTrigger?: number;
}

const NO_SKIP = new Set<string>();
/** Same control width for every label-left field, as in the schedule dialog. */
const HORIZONTAL_FIELD_WIDTH = '[&>[data-orientation=horizontal]>:last-child]:w-48';

export function CreateKnowledgeBaseDialog({
	open,
	onOpenChange,
	onCreated,
	onAddCredential,
	credentialRefetchTrigger,
}: Props) {
	const { t } = useTranslation();
	const { create } = useKnowledgeBases();
	const {
		providers,
		policy,
		loading,
		refetch: refetchModels,
	} = useKbEmbeddingModels(credentialRefetchTrigger);
	const { chunkers } = useChunkers();

	const [name, setName] = useState('');
	const [description, setDescription] = useState('');
	const [embeddingConfig, setEmbeddingConfig] = useState<EmbeddingModelConfig | null>(null);
	const [selectedChunkerType, setSelectedChunkerType] = useState<string>('');
	const [chunkerParams, setChunkerParams] = useState<Record<string, SchemaFormValue>>({});
	const [submitting, setSubmitting] = useState(false);
	const [errorKey, setErrorKey] = useState<string | null>(null);

	useEffect(() => {
		if (open) void refetchModels();
	}, [open, refetchModels]);

	const selectedChunker = useMemo<ChunkerInfo | null>(
		() => chunkers.find((c) => c.type === selectedChunkerType) ?? null,
		[chunkers, selectedChunkerType],
	);

	const chunkerParamSchema = useMemo<JSONSchema | null>(
		() => selectedChunker?.parameter_schema ?? null,
		[selectedChunker],
	);

	const handleSelectChunker = useCallback(
		(type: string) => {
			setSelectedChunkerType(type);
			const info = chunkers.find((c) => c.type === type);
			const schema = info?.parameter_schema;
			setChunkerParams(schema ? defaultValuesFromSchema(schema, NO_SKIP) : {});
		},
		[chunkers],
	);

	const handleChunkerParamChange = useCallback((key: string, value: SchemaFormValue) => {
		setChunkerParams((prev) => ({ ...prev, [key]: value }));
	}, []);

	// Default to the first available chunker so the form is submittable
	// without an explicit pick; re-pick when the list changes underneath.
	useEffect(() => {
		if (!open || chunkers.length === 0) return;
		if (!chunkers.some((c) => c.type === selectedChunkerType)) {
			handleSelectChunker(chunkers[0].type);
		}
	}, [open, chunkers, selectedChunkerType, handleSelectChunker]);

	useEffect(() => {
		if (!open) {
			setName('');
			setDescription('');
			setEmbeddingConfig(null);
			setSelectedChunkerType('');
			setChunkerParams({});
			setErrorKey(null);
			setSubmitting(false);
		}
	}, [open]);

	const handleSubmit = async () => {
		if (!name.trim()) {
			setErrorKey('dialog-knowledge-base-create.errors.nameRequired');
			return;
		}
		if (!embeddingConfig) {
			setErrorKey('dialog-knowledge-base-create.errors.embeddingRequired');
			return;
		}
		if (!selectedChunkerType) {
			setErrorKey('dialog-knowledge-base-create.errors.chunkerRequired');
			return;
		}
		setErrorKey(null);
		setSubmitting(true);
		try {
			const params: Record<string, unknown> = {};
			for (const [k, v] of Object.entries(chunkerParams)) {
				if (v !== undefined && v !== null && v !== '') params[k] = v;
			}
			const chunkerConfig: ChunkerConfig = {
				type: selectedChunkerType,
				parameters: params,
			};
			const knowledgeBaseId = await create({
				name: name.trim(),
				description: description.trim(),
				embedding_model_config: embeddingConfig,
				chunker_config: chunkerConfig,
			});
			onCreated?.(knowledgeBaseId);
			onOpenChange(false);
		} catch {
			// The API client displays the error while the form stays open.
		} finally {
			setSubmitting(false);
		}
	};

	const isLockedPolicy = policy && policy.kind !== 'any';
	const noCompatibleModels = !loading && providers.length === 0;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[500px] flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden supports-[height:100dvh]:max-h-[calc(100dvh-2rem)]">
				<DialogHeader className="shrink-0">
					<DialogTitle>{t('dialog-knowledge-base-create.title')}</DialogTitle>
					<DialogDescription>
						{t('dialog-knowledge-base-create.description')}
					</DialogDescription>
				</DialogHeader>

				<div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
					{isLockedPolicy && policy?.dimension != null && (
						<Alert>
							<Info className="size-4" />
							<AlertTitle>
								{t('dialog-knowledge-base-create.policy.lockedTitle', {
									dimension: policy.dimension,
								})}
							</AlertTitle>
							<AlertDescription>
								{t('dialog-knowledge-base-create.policy.lockedDescription', {
									dimension: policy.dimension,
								})}
							</AlertDescription>
						</Alert>
					)}

					{noCompatibleModels && (
						<Alert variant="destructive">
							<CircleAlert className="size-4" />
							<AlertTitle>
								{t('dialog-knowledge-base-create.policy.noCompatibleTitle')}
							</AlertTitle>
							<AlertDescription>
								{isLockedPolicy && policy?.dimension != null
									? t('dialog-knowledge-base-create.policy.noCompatibleLocked', {
											dimension: policy.dimension,
										})
									: t('dialog-knowledge-base-create.policy.noCompatibleAny')}
							</AlertDescription>
						</Alert>
					)}

					<FieldGroup className={HORIZONTAL_FIELD_WIDTH}>
						<Field>
							<FieldLabel>{t('dialog-knowledge-base-create.name.label')}</FieldLabel>
							<Input
								value={name}
								onChange={(e) => setName(e.target.value)}
								placeholder={t('dialog-knowledge-base-create.name.placeholder')}
								disabled={submitting}
							/>
						</Field>
						<Field>
							<FieldLabel>
								{t('dialog-knowledge-base-create.descriptionField.label')}
							</FieldLabel>
							<Textarea
								value={description}
								onChange={(e) => setDescription(e.target.value)}
								placeholder={t(
									'dialog-knowledge-base-create.descriptionField.placeholder',
								)}
								disabled={submitting}
								rows={3}
							/>
						</Field>

						<Separator />

						{open && (
							<EmbeddingSelect
								value={embeddingConfig}
								providers={providers}
								policy={policy}
								loading={loading}
								disabled={submitting}
								onChange={setEmbeddingConfig}
								onAddCredential={onAddCredential}
							/>
						)}

						{chunkers.length > 0 && (
							<>
								<Separator />

								<Field orientation="horizontal">
									<FieldLabel>
										{t('dialog-knowledge-base-create.chunker.label')}
									</FieldLabel>
									<ChunkerSelect
										value={selectedChunkerType}
										chunkers={chunkers}
										onChange={handleSelectChunker}
										disabled={submitting}
									/>
								</Field>

								{chunkerParamSchema && (
									<SchemaForm
										schema={chunkerParamSchema}
										values={chunkerParams}
										onChange={handleChunkerParamChange}
										skipFields={NO_SKIP}
										idPrefix="chunker-param"
										orientation="horizontal"
										className={HORIZONTAL_FIELD_WIDTH}
										labelFor={(key, prop) =>
											t(
												`chunker-types.${selectedChunkerType}.params.${key}.label`,
												{ defaultValue: '' },
											) ||
											prop.title ||
											undefined
										}
										descriptionFor={(key, prop) =>
											t(
												`chunker-types.${selectedChunkerType}.params.${key}.description`,
												{ defaultValue: '' },
											) ||
											prop.description ||
											undefined
										}
									/>
								)}
							</>
						)}

						{errorKey && <p className="text-destructive text-sm">{t(errorKey)}</p>}
					</FieldGroup>
				</div>
				<DialogFooter className="shrink-0">
					<Button
						variant="ghost"
						onClick={() => onOpenChange(false)}
						disabled={submitting}
					>
						<CircleAlert className="size-3.5" />
						{t('common.cancel')}
					</Button>
					<Button
						onClick={handleSubmit}
						disabled={submitting || loading || noCompatibleModels || !embeddingConfig}
					>
						{submitting ? (
							<Loader2 className="size-3.5 animate-spin" />
						) : (
							<PlusCircle className="size-3.5" />
						)}
						{submitting ? t('common.creating') : t('common.create')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

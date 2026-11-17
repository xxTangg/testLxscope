import { Ban, ChevronDown, PlusCircle } from 'lucide-react';

import type { ChatModelConfig } from '@/api';
import { LONGXIN_AI_LABEL } from '@/api/credential';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuGroup,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuPortal,
	DropdownMenuSeparator,
	DropdownMenuSub,
	DropdownMenuSubContent,
	DropdownMenuSubTrigger,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAvailableModels } from '@/hooks/useAvailableModels';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';
import { credentialLabel } from '@/utils/common';

interface Props extends Omit<React.ComponentPropsWithoutRef<typeof Button>, 'onChange' | 'value'> {
	value?: ChatModelConfig | null;
	onChange?: (value: ChatModelConfig | null) => void;
	onAddCredential?: () => void;
	placeholder?: string;
	allowClear?: boolean;
	clearLabel?: string;
}

export function LlmSelect({
	value,
	onChange,
	onAddCredential,
	placeholder,
	allowClear = false,
	clearLabel,
	className,
	...props
}: Props) {
	const { groups, loading } = useAvailableModels();
	const { t } = useTranslation();
	const credentials = Object.values(groups)
		.flat()
		.filter((entry) => entry.models.length > 0);
	const selected = credentials.find((entry) => entry.credential.id === value?.credential_id);
	const displayLabel = value?.model
		? selected && credentials.length > 1
			? credentialLabel(selected.credential) + ' · ' + value.model
			: value.model
		: loading
			? t('llm-select.loading')
			: (placeholder ?? t('llm-select.placeholder'));

	const modelItems = ({ credential, models }: (typeof credentials)[number]) =>
		models.map((model) => (
			<DropdownMenuItem
				key={model.name}
				onSelect={() =>
					onChange?.({
						type: String(credential.data.type),
						credential_id: credential.id,
						model: model.name,
						parameters: {},
					})
				}
			>
				{model.label || model.name}
			</DropdownMenuItem>
		));

	return (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>
				<Button
					variant="outline"
					size="sm"
					className={cn('justify-between gap-1 font-normal', className)}
					{...props}
				>
					<span className="truncate">{displayLabel}</span>
					<ChevronDown className="size-3.5 text-muted-foreground" />
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="start" className="max-h-72 min-w-48 overflow-y-auto">
				{!loading && credentials.length === 0 ? (
					<div className="px-2 py-3 text-center text-sm text-muted-foreground">
						<p className="font-medium">{t('llm-select.empty.title')}</p>
						<p className="mt-1 text-xs">{t('llm-select.empty.description')}</p>
					</div>
				) : (
					<DropdownMenuGroup>
						<DropdownMenuLabel>{LONGXIN_AI_LABEL}</DropdownMenuLabel>
						{credentials.length === 1
							? modelItems(credentials[0])
							: credentials.map((entry) => (
									<DropdownMenuSub key={entry.credential.id}>
										<DropdownMenuSubTrigger>
											{credentialLabel(entry.credential)}
										</DropdownMenuSubTrigger>
										<DropdownMenuPortal>
											<DropdownMenuSubContent className="max-h-60 overflow-y-auto">
												{modelItems(entry)}
											</DropdownMenuSubContent>
										</DropdownMenuPortal>
									</DropdownMenuSub>
								))}
					</DropdownMenuGroup>
				)}
				<DropdownMenuSeparator />
				{allowClear && (
					<DropdownMenuItem disabled={!value} onSelect={() => onChange?.(null)}>
						<Ban className="size-4" />
						{clearLabel ?? t('llm-select.clear')}
					</DropdownMenuItem>
				)}
				<DropdownMenuItem onSelect={onAddCredential}>
					<PlusCircle className="size-4" />
					{t('llm-select.addCredential')}
				</DropdownMenuItem>
			</DropdownMenuContent>
		</DropdownMenu>
	);
}

import type { ContextWindowUsage } from '@/api';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

const categories = [
	{ key: 'system_tokens', label: 'system', color: 'bg-sky-500' },
	{ key: 'tool_tokens', label: 'tools', color: 'bg-indigo-500' },
	{ key: 'message_tokens', label: 'messages', color: 'bg-teal-500' },
	{ key: 'summary_tokens', label: 'summary', color: 'bg-amber-500' },
] as const;

export function ContextWindowIndicator({ usage }: { usage: ContextWindowUsage | null }) {
	const { t, i18n } = useTranslation();
	const number = new Intl.NumberFormat(i18n.language);
	const percent = new Intl.NumberFormat(i18n.language, { style: 'percent' });
	const usedRatio = usage ? usage.used_tokens / usage.context_size : 0;
	const trigger = usage ? percent.format(usage.trigger_ratio) : null;

	return (
		<Popover>
			<PopoverTrigger asChild>
				<Button
					type="button"
					variant="ghost"
					size="sm"
					className="gap-2 text-muted-foreground"
					aria-label={t('chat.contextWindow.title') + (usage ? ` ${percent.format(usedRatio)}` : '')}
				>
					<span aria-hidden className="h-1.5 w-10 overflow-hidden rounded-full bg-foreground/10">
						<span
							className={cn(
								'block h-full rounded-full bg-teal-500',
								usage && usedRatio >= usage.trigger_ratio && 'bg-amber-500',
							)}
							style={{ width: `${Math.min(usedRatio, 1) * 100}%` }}
						/>
					</span>
					{t('chat.contextWindow.shortLabel')}
					<span className="font-mono tabular-nums">{usage ? percent.format(usedRatio) : '—'}</span>
				</Button>
			</PopoverTrigger>
			<PopoverContent
				side="top"
				align="end"
				sideOffset={8}
				className="max-h-[var(--radix-popover-content-available-height)] w-80 max-w-[calc(100dvw_-_1.5rem)] gap-3 overflow-y-auto p-4"
				aria-label={t('chat.contextWindow.title')}
			>
				<h2 className="font-medium">{t('chat.contextWindow.title')}</h2>
				{usage ? (
					<>
						<p className="text-xs text-muted-foreground">
							{t('chat.contextWindow.estimate', {
								used: number.format(usage.used_tokens),
								capacity: number.format(usage.context_size),
							})}
						</p>
						<div aria-hidden className="relative flex h-2 overflow-hidden rounded-full bg-foreground/10">
							{categories.map(({ key, color }) => (
								<span
									key={key}
									className={cn('h-full shrink-0', color)}
									style={{ width: `${(usage[key] / usage.context_size) * 100}%` }}
								/>
							))}
							<span
								className="absolute inset-y-0 w-0.5 bg-foreground/70"
								style={{ left: `${usage.trigger_ratio * 100}%` }}
							/>
						</div>
						<dl className="space-y-2 text-xs">
							{categories.map(({ key, label, color }) => (
								<div key={key} className="flex items-center justify-between gap-2">
									<dt className="flex items-center gap-2">
										<span aria-hidden className={cn('size-2 rounded-full', color)} />
										{t(`chat.contextWindow.${label}`)}
									</dt>
									<dd className="flex gap-2 font-mono tabular-nums text-muted-foreground">
										<span>{number.format(usage[key])}</span>
										<span className="w-8 text-right">{percent.format(usage[key] / usage.context_size)}</span>
									</dd>
								</div>
							))}
						</dl>
						<p className="flex justify-between border-t pt-2 text-xs text-muted-foreground">
							<span>{t('chat.contextWindow.autoCompression')}</span>
							<span className="font-mono tabular-nums">{trigger}</span>
						</p>
					</>
				) : (
					<p className="text-xs text-muted-foreground">{t('chat.contextWindow.unavailable')}</p>
				)}
			</PopoverContent>
		</Popover>
	);
}

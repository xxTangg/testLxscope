import { Check, CircleAlert, CircleDashed, Clock3, Loader2, Pause, Square } from 'lucide-react';

import type { SOPPhase } from '@/api';
import { useTranslation } from '@/i18n/useI18n';
import { cn } from '@/lib/utils';

const styles: Record<SOPPhase, string> = {
	pending: 'bg-muted text-muted-foreground',
	running: 'bg-blue-500/8 text-blue-600 dark:text-blue-400',
	awaiting: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
	completed: 'bg-emerald-500/8 text-emerald-700 dark:text-emerald-400',
	failed: 'bg-destructive/8 text-destructive',
	blocked: 'bg-muted text-muted-foreground',
	retry_wait: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
	cancelled: 'bg-muted text-muted-foreground',
};

export function SOPStatus({
	phase = 'pending',
	iconOnly = false,
}: {
	phase?: SOPPhase;
	iconOnly?: boolean;
}) {
	const { t } = useTranslation();
	const Icon = {
		pending: CircleDashed,
		running: Loader2,
		awaiting: Pause,
		completed: Check,
		failed: CircleAlert,
		blocked: Pause,
		retry_wait: Clock3,
		cancelled: Square,
	}[phase];
	return (
		<span
			className={cn(
				'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md text-xs font-medium',
				styles[phase],
				iconOnly ? 'size-7' : 'px-2 py-1',
			)}
			title={t(`sop.phase.${phase}`)}
		>
			<Icon
				className={cn(
					'size-3.5',
					phase === 'running' && 'animate-spin motion-reduce:animate-none',
				)}
			/>
			{iconOnly ? (
				<span className="sr-only">{t(`sop.phase.${phase}`)}</span>
			) : (
				t(`sop.phase.${phase}`)
			)}
		</span>
	);
}

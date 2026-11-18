import { Check, Copy } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { useTranslation } from '@/i18n/useI18n';
import { copyToClipboard } from '@/utils/common';

export function DiagnosticReference({ id }: { id: string }) {
	const { t } = useTranslation();
	const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

	return (
		<div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
			<span>
				{t('diagnostic.reference')} <code className="select-all break-all">{id}</code>
			</span>
			<Button
				type="button"
				variant="ghost"
				size="xs"
				onClick={async () => setCopyState((await copyToClipboard(id)) ? 'copied' : 'failed')}
			>
				{copyState === 'copied' ? <Check /> : <Copy />}
				{t(copyState === 'copied' ? 'diagnostic.copied' : 'diagnostic.copy')}
			</Button>
			{copyState === 'failed' && <span role="status">{t('diagnostic.copyFailed')}</span>}
		</div>
	);
}

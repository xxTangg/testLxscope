import { useEffect, useState } from 'react';

import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';

/** Keep invalid drafts visible and prevent saving until they are corrected. */
export function SOPJsonField({
	value,
	onChange,
	onValidity,
	label,
	stringValues = false,
}: {
	value: Record<string, unknown> | null | undefined;
	onChange: (value: Record<string, unknown>) => void;
	onValidity: (valid: boolean) => void;
	label: string;
	stringValues?: boolean;
}) {
	const { t } = useTranslation();
	const [draft, setDraft] = useState(() => JSON.stringify(value ?? {}, null, 2));
	const [invalid, setInvalid] = useState(false);
	useEffect(() => {
		if (invalid) return;
		try {
			if (JSON.stringify(JSON.parse(draft || '{}')) !== JSON.stringify(value ?? {})) {
				setDraft(JSON.stringify(value ?? {}, null, 2));
			}
		} catch {
			/* Keep an unfinished draft while the user types. */
		}
	}, [draft, invalid, value]);
	return (
		<label className="block space-y-2 text-sm">
			<span className="text-xs font-medium text-text-secondary">{label}</span>
			<Textarea
				className="min-h-24 bg-muted/30 font-mono text-xs leading-relaxed"
				spellCheck={false}
				value={draft}
				aria-invalid={invalid}
				onChange={(event) => {
					setDraft(event.target.value);
					try {
						const parsed: unknown = JSON.parse(event.target.value || '{}');
						if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object')
							throw new Error('object required');
						if (
							stringValues &&
							Object.values(parsed).some((source) => typeof source !== 'string')
						)
							throw new Error('string bindings required');
						onChange(parsed as Record<string, unknown>);
						setInvalid(false);
						onValidity(true);
					} catch {
						setInvalid(true);
						onValidity(false);
					}
				}}
			/>
			{invalid && (
				<span role="alert" className="block text-xs text-destructive">
					{t(stringValues ? 'sop.stringBindingsRequired' : 'sop.jsonObjectRequired')}
				</span>
			)}
		</label>
	);
}

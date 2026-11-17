import type { SessionRecord } from '@/api';

/** Session timestamps use UTC on the wire and Beijing time in the UI. */
export const SESSION_TIME_ZONE = 'Asia/Shanghai';

const formatter = new Intl.DateTimeFormat('en-GB', {
	timeZone: SESSION_TIME_ZONE,
	year: 'numeric',
	month: '2-digit',
	day: '2-digit',
	hour: '2-digit',
	minute: '2-digit',
	second: '2-digit',
	hour12: false,
});

/** Older Docker/SQL records omitted their UTC offset. Never infer browser time. */
export function parseSessionTime(value: string): Date {
	const normalized = value
		.trim()
		.replace(' ', 'T')
		.replace(/(\.\d{3})\d+/, '$1');
	return new Date(/(?:z|[+-]\d{2}:?\d{2})$/i.test(normalized) ? normalized : normalized + 'Z');
}

function displayParts(date: Date): Record<string, string> | null {
	if (Number.isNaN(date.getTime())) return null;
	const parts: Record<string, string> = {};
	for (const part of formatter.formatToParts(date)) parts[part.type] = part.value;
	return parts;
}

function dateKey(parts: Record<string, string>): string {
	return `${parts.year}-${parts.month}-${parts.day}`;
}

export function formatSessionTime(
	value: string,
	style: 'datetime' | 'time' | 'date' = 'datetime',
): string {
	const parts = displayParts(parseSessionTime(value));
	if (!parts) return '—';
	if (style === 'date') return dateKey(parts);
	if (style === 'time') return `${parts.hour}:${parts.minute}`;
	return `${dateKey(parts)} ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function isSessionToday(value: string, now = new Date()): boolean {
	const parts = displayParts(parseSessionTime(value));
	const today = displayParts(now);
	return parts !== null && today !== null && dateKey(parts) === dateKey(today);
}

/** Localize automatic timestamp placeholders; keep user and generated titles. */
export function sessionDisplayName(session: SessionRecord): string {
	const { name, naming } = session.config;
	if (naming?.auto && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(name)) {
		return formatSessionTime(session.created_at);
	}
	return name || session.id;
}

/**
 * Create a UUID without requiring the page to be served from a secure context.
 *
 * `crypto.randomUUID()` is unavailable on ordinary HTTP pages in browsers,
 * while `crypto.getRandomValues()` remains available there.
 */
export function createUuid(): string {
	const cryptoApi = typeof globalThis.crypto !== 'undefined' ? globalThis.crypto : undefined;

	if (typeof cryptoApi?.randomUUID === 'function') {
		return cryptoApi.randomUUID();
	}

	if (typeof cryptoApi?.getRandomValues === 'function') {
		const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
		bytes[6] = (bytes[6] & 0x0f) | 0x40;
		bytes[8] = (bytes[8] & 0x3f) | 0x80;
		const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
		return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
	}

	// This is only for very old environments without Web Crypto support.
	return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
		const random = Math.floor(Math.random() * 16);
		const value = character === 'x' ? random : (random & 0x3) | 0x8;
		return value.toString(16);
	});
}

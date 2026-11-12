const EXTENSIONS_BY_MEDIA_TYPE: Record<string, string> = {
	'application/json': 'json',
	'application/msword': 'doc',
	'application/pdf': 'pdf',
	'application/vnd.ms-excel': 'xls',
	'application/vnd.ms-powerpoint': 'ppt',
	'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
	'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
	'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
	'application/zip': 'zip',
	'audio/mp4': 'm4a',
	'audio/mpeg': 'mp3',
	'audio/wav': 'wav',
	'image/gif': 'gif',
	'image/heic': 'heic',
	'image/jpeg': 'jpg',
	'image/png': 'png',
	'image/svg+xml': 'svg',
	'image/tiff': 'tiff',
	'image/webp': 'webp',
	'text/csv': 'csv',
	'text/html': 'html',
	'text/markdown': 'md',
	'text/plain': 'txt',
	'text/tab-separated-values': 'tsv',
	'text/xml': 'xml',
	'video/mp4': 'mp4',
	'video/quicktime': 'mov',
	'video/webm': 'webm',
	'video/x-msvideo': 'avi',
};

export function extensionForMediaType(mediaType: string): string {
	const normalized = mediaType.toLowerCase().split(';')[0].trim();
	if (EXTENSIONS_BY_MEDIA_TYPE[normalized]) return EXTENSIONS_BY_MEDIA_TYPE[normalized];
	const subtype = normalized.split('/')[1]?.split('+')[0];
	return subtype && !subtype.startsWith('vnd.') ? subtype.replace(/^x-/, '') : 'bin';
}

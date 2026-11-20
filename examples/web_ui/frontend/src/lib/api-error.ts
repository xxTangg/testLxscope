import i18n from '../i18n/index.ts';

// Existing API releases and saved task runs contain English error strings.
// Match messages the application owns and keep the original API detail for diagnostics.
const knownErrors = new Map([
	['A node conversation is still running.', 'sop.errors.conversationRunning'],
	['Cancelled runs cannot be retried.', 'sop.errors.cancelledRetry'],
	['This run was cancelled.', 'sop.errors.cancelled'],
	['This run is cancelled.', 'sop.errors.cancelled'],
	['The node changed; refresh before retrying.', 'sop.errors.nodeChanged'],
	['Only failed, completed or parked nodes can be retried.', 'sop.errors.nodeCannotRetry'],
	['Downstream results exist; choose rerun node and descendants.', 'sop.errors.downstreamResults'],
	['Wait for affected running nodes to stop before rerunning them.', 'sop.errors.nodesRunning'],
	['This node is waiting for a tool, not a human verdict.', 'sop.errors.waitingForTool'],
	['The submission changed; refresh before reviewing it.', 'sop.errors.submissionChanged'],
	['Node execution timed out.', 'sop.errors.nodeTimeout'],
	['Worker stopped before completing the node.', 'sop.errors.workerStopped'],
	['Recovered after worker interruption.', 'sop.errors.workerRecovered'],
	['An upstream node needs attention.', 'sop.errors.upstreamBlocked'],
	['Cancelled by the owner.', 'sop.errors.cancelled'],
	['The SOP graph contains a cycle.', 'sop.cycleError'],
	['Node ids must be unique.', 'sop.errors.duplicateNodeIds'],
	['Enter the API key for this gateway address.', 'apiError.gatewayKeyRequired'],
	['Enter the gateway API key.', 'apiError.gatewayKeyRequired'],
	['Enter a valid gateway address.', 'apiError.invalidGatewayAddress'],
	['The gateway changed. Confirm the chat models for the new connection.', 'apiError.gatewayChanged'],
	['Directory not found.', 'apiError.directoryNotFound'],
	['Requested path is a file, not a directory.', 'apiError.expectDirectory'],
	['File not found.', 'apiError.fileNotFound'],
	['Requested path is a directory, not a file.', 'apiError.expectFile'],
	['WebRTC microphone capture is not available in this browser.', 'realtime.microphoneUnavailable'],
	['The realtime control channel was closed.', 'realtime.connectionLost'],
	['The realtime media connection was lost.', 'realtime.connectionLost'],
	['The browser blocked realtime audio playback.', 'realtime.playbackBlocked'],
	['Timed out while gathering WebRTC network candidates.', 'realtime.connectionTimeout'],
	['Timed out while opening the realtime connection.', 'realtime.connectionTimeout'],
]);

const stepErrors = [
	[/^Step (\d+) is not part of this run\.$/, 'sop.errors.stepNotFound'],
	[/^Step (\d+) is not judged by a person\.$/, 'sop.errors.stepNotHumanReviewed'],
	[/^Step (\d+) is not waiting to be judged\.$/, 'sop.errors.stepNotAwaitingReview'],
] as const;

const errorPatterns = [
	[/^These conversations are used but never configured: (.+)\.$/, 'sop.errors.sessionsNotConfigured'],
	[/^Unknown dependency ['"](.+)['"]\.$/, 'sop.errors.unknownDependency'],
	[/^Attachment exceeds the (\d+)-byte size limit\.$/, 'apiError.attachmentTooLarge'],
	[/^.+ Pass a different 'name' to install it alongside the existing one\.$/, 'apiError.installNameTaken'],
] as const;

export function translateKnownError(detail: string): string | undefined {
	const text = detail.trim();
	const key = knownErrors.get(text);
	if (key) return i18n.t(key);
	for (const [pattern, translation] of stepErrors) {
		const match = text.match(pattern);
		if (match) return i18n.t(translation, { value: Number(match[1]) + 1 });
	}
	for (const [pattern, translation] of errorPatterns) {
		const match = text.match(pattern);
		if (match) return i18n.t(translation, { value: match[1] });
	}
	return undefined;
}

const startsInChinese = (detail: string) => /^\s*[“「【]?\p{Script=Han}/u.test(detail);

const validationTypes = new Map([
	['missing', 'required'],
	['string_type', 'text'],
	['int_type', 'integer'],
	['int_parsing', 'integer'],
	['bool_type', 'boolean'],
	['bool_parsing', 'boolean'],
	['json_invalid', 'invalidJson'],
]);

function formatValidationErrors(detail: string): string | undefined {
	let errors: unknown;
	try {
		errors = JSON.parse(detail);
	} catch {
		return undefined;
	}
	if (!Array.isArray(errors)) return undefined;
	const messages = errors.flatMap((entry: unknown) => {
		if (!entry || typeof entry !== 'object' || !('msg' in entry)) return [];
		const { type, loc, msg } = entry as { type?: string; loc?: unknown; msg: unknown };
		if (typeof msg !== 'string') return [];
		const field = Array.isArray(loc) ? loc.slice(1).join('.') : '';
		const messageKey = validationTypes.get(type ?? '') ?? 'invalid';
		const message =
			translateKnownError(msg.replace(/^Value error, /, '')) ??
			(startsInChinese(msg) ? msg : i18n.t(`apiError.validation.${messageKey}`));
		return field ? i18n.t('apiError.validation.field', { field, message }) : message;
	});
	return messages.length ? messages.join('\n') : undefined;
}

export function formatApiErrorMessage(status: number, detail: string): string {
	return (
		translateKnownError(detail) ??
		(status === 422 ? formatValidationErrors(detail) : undefined) ??
		(startsInChinese(detail)
			? detail
			: i18n.t(`apiError.status.${status}`, {
					defaultValue: i18n.t('apiError.requestFailed', { status }),
				}))
	);
}

export function formatApiErrorForAlert(err: unknown, fallback?: string): string {
	const message = err instanceof Error ? err.message : String(err);
	return translateKnownError(message) ?? (startsInChinese(message) ? message : (fallback ?? message));
}

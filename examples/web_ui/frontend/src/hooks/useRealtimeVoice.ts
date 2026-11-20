import type { UserConfirmResultEvent } from '@agentscope-ai/agentscope/event';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/api/client';
import i18n from '@/i18n';
import { formatApiErrorForAlert } from '@/lib/api-error';
import { BrowserWebRTCTransport, type RealtimeConnectionState } from '@/lib/browserWebRTCTransport';

function describeVoiceError(error: unknown): string {
	if (error instanceof ApiError) return error.message;
	if (error instanceof DOMException && error.name === 'NotAllowedError') {
		return i18n.t('realtime.microphoneDenied');
	}
	return formatApiErrorForAlert(error, i18n.t('realtime.connectionError'));
}

export function useRealtimeVoice(agentId: string | null, sessionId: string | null) {
	const [state, setState] = useState<RealtimeConnectionState>('idle');
	const transportRef = useRef<BrowserWebRTCTransport | null>(null);

	const stop = useCallback(async () => {
		const transport = transportRef.current;
		transportRef.current = null;
		if (transport) await transport.stop();
		setState('idle');
	}, []);

	useEffect(() => {
		setState('idle');
		return () => {
			const transport = transportRef.current;
			if (transport) {
				transportRef.current = null;
				void transport.stop();
			}
		};
	}, [agentId, sessionId]);

	const start = useCallback(async () => {
		if (!agentId || !sessionId || transportRef.current) return;
		const transport = new BrowserWebRTCTransport({
			agentId,
			sessionId,
			onStateChange: (nextState) => {
				if (transportRef.current === transport) setState(nextState);
			},
			onError: (error) => {
				if (transportRef.current !== transport) return;
				transportRef.current = null;
				setState('error');
				toast.error(describeVoiceError(error));
			},
		});
		transportRef.current = transport;
		try {
			await transport.start();
		} catch (error) {
			await transport.stop();
			if (transportRef.current === transport) {
				transportRef.current = null;
				setState('error');
				toast.error(describeVoiceError(error));
			}
		}
	}, [agentId, sessionId]);

	const toggle = useCallback(async () => {
		if (state === 'active' || state === 'connecting') await stop();
		else await start();
	}, [start, state, stop]);

	const userConfirm = useCallback(async (event: UserConfirmResultEvent) => {
		const transport = transportRef.current;
		if (!transport) throw new Error('Realtime voice mode is not active.');
		transport.userConfirm(event);
	}, []);

	return { state, toggle, userConfirm };
}

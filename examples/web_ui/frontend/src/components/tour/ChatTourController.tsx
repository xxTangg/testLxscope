import { useOnborda } from 'onborda';
import { useEffect, useRef } from 'react';

import { CHAT_TOUR_NAME } from './chatTourSteps';
import { useAuth } from '@/hooks/useAuth';

interface Props {
	ready: boolean;
	sessionsCount: number;
	onEnsureSidebarOpen: () => void;
}

const FORCE_TOUR_KEY = 'force_tour';

export const ChatTourController = ({ ready, sessionsCount, onEnsureSidebarOpen }: Props) => {
	const { autoTourPending, clearAutoTour } = useAuth();
	const { currentStep, currentTour, setCurrentStep, startOnborda, closeOnborda } = useOnborda();
	const sessionsAtStepStart = useRef(sessionsCount);

	// Wait for account data and a valid selection before starting the tour.
	useEffect(() => {
		if (!ready) return;
		const force = sessionStorage.getItem(FORCE_TOUR_KEY) === '1';
		if (!force && !autoTourPending) return;
		onEnsureSidebarOpen();
		const timer = window.setTimeout(() => {
			sessionStorage.removeItem(FORCE_TOUR_KEY);
			clearAutoTour();
			startOnborda(CHAT_TOUR_NAME);
		}, 300);
		return () => window.clearTimeout(timer);
	}, [ready, autoTourPending, clearAutoTour, onEnsureSidebarOpen, startOnborda]);

	useEffect(() => () => closeOnborda(), [closeOnborda]);

	useEffect(() => {
		if (currentTour === CHAT_TOUR_NAME && currentStep === 1) {
			sessionsAtStepStart.current = sessionsCount;
		}
		// Snapshot on entering the step, not when a new session arrives.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [currentStep, currentTour]);

	useEffect(() => {
		if (
			currentTour === CHAT_TOUR_NAME &&
			currentStep === 1 &&
			sessionsCount > sessionsAtStepStart.current
		)
			setCurrentStep(2);
	}, [sessionsCount, currentStep, currentTour, setCurrentStep]);

	return null;
};

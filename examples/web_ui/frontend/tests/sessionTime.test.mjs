import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
	formatSessionTime,
	isSessionToday,
	parseSessionTime,
	sessionDisplayName,
} from '../src/utils/sessionTime.ts';

test('legacy UTC, explicit UTC and offset timestamps identify the same instant', () => {
	const expected = Date.parse('2026-11-13T06:51:38.123Z');
	for (const value of [
		'2026-11-13T06:51:38.123456',
		'2026-11-13 06:51:38.123456',
		'2026-11-13T06:51:38.123456Z',
		'2026-11-13T06:51:38.123+00:00',
		'2026-11-13T14:51:38.123+08:00',
	]) {
		assert.equal(parseSessionTime(value).getTime(), expected, value);
	}
});

test('session time always displays in Beijing time, regardless of browser timezone', () => {
	assert.equal(formatSessionTime('2026-11-13T06:51:38'), '2026-11-13 14:51:38');
	assert.equal(formatSessionTime('2026-11-13T06:51:38Z', 'time'), '14:51');
	assert.equal(formatSessionTime('2026-11-13T18:51:38Z', 'date'), '2026-11-14');
});

test('today and earlier split at Beijing midnight, including year boundaries', () => {
	const now = new Date('2026-12-31T16:00:01Z');
	assert.equal(isSessionToday('2026-12-31T16:00:00', now), true);
	assert.equal(isSessionToday('2026-12-31T15:59:59.999999Z', now), false);
	assert.equal(formatSessionTime('2026-12-31T16:00:00Z'), '2027-01-01 00:00:00');
});

test('automatic timestamp title agrees with the session timestamp', () => {
	const session = {
		id: 'session-1',
		created_at: '2026-11-13T06:51:38.999999',
		config: { name: '2026-11-13 06:51:38', naming: { auto: true } },
	};
	assert.equal(sessionDisplayName(session), '2026-11-13 14:51:38');
	assert.equal(session.config.name, '2026-11-13 06:51:38');
});

test('manual timestamp names and generated conversation titles are preserved', () => {
	const session = {
		id: 'session-1',
		created_at: '2026-11-13T06:51:38Z',
		config: { name: '2026-11-13 06:51:38', naming: { auto: false } },
	};
	assert.equal(sessionDisplayName(session), '2026-11-13 06:51:38');
	session.config.name = 'SQL update review';
	assert.equal(sessionDisplayName(session), 'SQL update review');
	session.config.name = '';
	assert.equal(sessionDisplayName(session), 'session-1');
});

test('invalid timestamps cannot crash the session list', () => {
	assert.equal(formatSessionTime('invalid'), '—');
	assert.equal(isSessionToday('invalid'), false);
});

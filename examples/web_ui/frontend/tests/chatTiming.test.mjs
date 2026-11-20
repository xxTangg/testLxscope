import assert from 'node:assert/strict';
import { test } from 'node:test';

import { formatElapsedTime } from '../src/utils/common.ts';

test('chat elapsed time displays whole seconds while running and after completion', () => {
	const start = '2026-11-19T14:00:00.000+08:00';
	const now = Date.parse(start) + 999;
	assert.equal(formatElapsedTime(start, null, now), '0s');
	assert.equal(formatElapsedTime(start, '2026-11-19T14:00:00.999+08:00', now), '0s');
	assert.equal(formatElapsedTime(start, null, now + 1), '1s');
	assert.equal(formatElapsedTime(start, '2026-11-19T14:01:02.999+08:00', now), '1m2s');
});

test('a reply started on the previous UTC deployment can finish in Beijing time', () => {
	const legacyStart = '2026-11-19T06:00:00.000';
	const finish = '2026-11-19T14:00:02.000+08:00';
	const now = Date.parse(finish);
	assert.equal(formatElapsedTime(legacyStart, null, now), '2s');
	assert.equal(formatElapsedTime(legacyStart, finish, now), '2s');
});

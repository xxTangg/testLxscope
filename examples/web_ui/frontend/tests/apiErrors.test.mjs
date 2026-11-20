import assert from 'node:assert/strict';
import { test } from 'node:test';

import { toast } from 'sonner';

import { ApiError, client } from '../src/api/client.ts';
import { formatApiErrorForAlert, translateKnownError } from '../src/lib/api-error.ts';

test('continuing a running SOP shows the Chinese warning and keeps the backend detail', async (t) => {
	const previousWindow = globalThis.window;
	const previousStorage = globalThis.localStorage;
	globalThis.window = { location: { origin: 'http://localhost' } };
	globalThis.localStorage = { getItem: () => null };
	t.after(() => {
		globalThis.window = previousWindow;
		globalThis.localStorage = previousStorage;
	});

	const detail = 'A node conversation is still running.';
	const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ detail }, { status: 409 }));
	const showError = t.mock.method(toast, 'error', () => {});
	const path = '/sop/runs/run-1/resume';
	const message = '仍有步骤会话正在运行，请等它结束后再点「继续运行」。';

	await assert.rejects(client.post(path, {}), (error) => {
		assert.ok(error instanceof ApiError);
		assert.equal(error.status, 409);
		assert.equal(error.detail, detail);
		assert.equal(formatApiErrorForAlert(error), message);
		return true;
	});
	assert.equal(fetch.mock.calls[0].arguments[0], 'http://localhost/api/sop/runs/run-1/resume');
	assert.deepEqual(showError.mock.calls[0].arguments, [message]);
	await assert.rejects(client.post(path, {}, undefined, { silent: true }), ApiError);
	assert.equal(showError.mock.callCount(), 1);
});

test('request errors and validation failures use Chinese while retaining field names and raw details', () => {
	const detail = JSON.stringify([{ type: 'missing', loc: ['body', 'name'], msg: 'Field required' }]);
	const error = new ApiError(422, detail);
	assert.equal(error.message, 'name：此项为必填项。');
	assert.equal(error.detail, detail);
	assert.equal(new ApiError(0, 'Network error').message, '无法连接到服务器，请检查网络后重试。');
	assert.equal(new ApiError(502, '<html>Bad Gateway</html>').message, '暂时无法连接到后端服务，请稍后重试。');
	assert.equal(new ApiError(400, '请先选择模型。').message, '请先选择模型。');
});

test('historical SOP messages and step-specific conflicts have localized text', () => {
	assert.equal(translateKnownError('Node execution timed out.'), '步骤执行超时。');
	assert.equal(new ApiError(409, 'Step 0 is not waiting to be judged.').message, '第 1 个步骤当前未在等待审核。');
	assert.equal(translateKnownError('Reviewer feedback'), undefined);
});

test('voice alerts use a known translation or the localized fallback', () => {
	assert.equal(
		formatApiErrorForAlert(new Error('The realtime media connection was lost.')),
		'语音连接已断开，请重新开始语音对话。',
	);
	assert.equal(formatApiErrorForAlert(new Error('Unrecognized provider error'), '语音连接失败。'), '语音连接失败。');
});

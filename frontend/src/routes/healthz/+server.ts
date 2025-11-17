import type { RequestHandler } from '@sveltejs/kit';

export const GET: RequestHandler = () =>
	new Response('ok', {
		status: 200,
		headers: { 'content-type': 'text/plain' }
	});
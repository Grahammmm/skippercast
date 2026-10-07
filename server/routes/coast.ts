import {Hono} from 'hono';
import {serveCoastData} from '../coast-data.ts';
import {rateLimit} from '../middleware/rate-limit.ts';
import type {AppEnv} from '../env.ts';

export const coastData = new Hono<AppEnv>();
coastData.all('/api/coast/*', rateLimit('FEED_LIMITER', 'coast'), c => serveCoastData(c.req.raw));
coastData.all('/coast-data/*', rateLimit('FEED_LIMITER', 'coast'), c => serveCoastData(c.req.raw));

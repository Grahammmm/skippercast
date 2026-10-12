// FE-75 type test (tests/test_coast_markup.mjs runs tsc on this file): CoastMarkup
// takes the name of an allow-listed packages/coast renderer and that renderer's
// own arguments, never a function, a look-alike name or raw markup. Every
// expected error below must occur, or tsc reports its directive as unused.
import {chart} from '../../../packages/coast/src/charts/series.ts';
import {CoastMarkup, coastMarkup} from '../../../web/app/CoastMarkup.tsx';

const args: Parameters<typeof chart> = [[], '2026-10-05T00:00:00Z', '2026-10-06T00:00:00Z', '2026-10-05T12:00:00Z', 'UTC'];

export const listed = <CoastMarkup renderer="chart" args={args} onCursor={(hour: string) => void hour} />;
export const markup: string = coastMarkup('chart', args);

// @ts-expect-error historyView is not on the allow-list yet
export const unlisted = <CoastMarkup renderer="historyView" args={args} />;
// @ts-expect-error a function is never accepted, only an allow-listed name
export const fn = <CoastMarkup renderer={chart} args={args} />;
// @ts-expect-error a look-alike name is not a renderer
export const lookalike = coastMarkup('svg', args);
// @ts-expect-error the arguments are the renderer's own
export const wrongArgs = <CoastMarkup renderer="chart" args={['<b>raw</b>']} />;
// @ts-expect-error there is no raw markup prop
export const raw = <CoastMarkup renderer="chart" args={args} html="<b>raw</b>" />;

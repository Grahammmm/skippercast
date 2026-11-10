// SC1407-09: opt-in for semantic suites that import web/ modules directly and render Spanish synchronously:
// the real Spanish table is installed (web/i18n-catalogue.ts prepareCatalogue) before the importing test runs.
import {prepareCatalogue} from '../../web/i18n-catalogue.ts';
await prepareCatalogue('es');

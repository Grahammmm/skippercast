import english from './status-strings.generated.json' with {type: 'json'};
import {lookup} from '../web/i18n-core.ts';
import {bilingual, initReadyLanguage} from '../web/i18n-catalogue.ts';

const strings = bilingual(english);
export const publicPageText = (id, lang = 'en', vars = {}) => lookup(strings, id, lang, vars);

/** Follow /status: leave authored English intact and translate static hosts before reading feeds. */
export async function readPublicPageLanguage(doc, page) {
  const lang = await initReadyLanguage();
  if (lang === 'en') return lang;
  doc.title = publicPageText(page + '.title', lang);
  for (const el of doc.querySelectorAll('[data-i18n]')) el.textContent = publicPageText(el.getAttribute('data-i18n'), lang);
  for (const el of doc.querySelectorAll('[data-i18n-lead]')) el.firstChild.nodeValue = publicPageText(el.getAttribute('data-i18n-lead'), lang) + ' ';
  for (const el of doc.querySelectorAll('[data-i18n-aria]')) el.setAttribute('aria-label', publicPageText(el.getAttribute('data-i18n-aria'), lang));
  return lang;
}

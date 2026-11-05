import {seasonYear} from '../season.ts';
import {ruleProfile, type RulesRegion} from '../regs.ts';
import {language, t, type StringId} from '../i18n.ts';
import './season.css';
export function SeasonStrip({data, species, region, year}: {data: any; species: string; region: RulesRegion; year: number}) {
  const lang = language.value, season = seasonYear(data, species, region, year, lang);
  if (!season) return null;
  const name = species === 'reef' ? 'Lingcod & rockfish' : ruleProfile(data, species, region).name;
  return <section class="app-season" aria-label={t('season.aria', lang, {name, year})}>
    <h4>{t('season.heading', lang, {name, year})}</h4>
    <ol>{season.months.map(m => <li key={m.month} data-state={m.state}><span>{t(`season.month.${m.month}` as StringId, lang)}</span> <span>{m.label}</span></li>)}</ol>
    <p>{t('season.footer', lang, {revision: season.revision})}<a href={season.link.href} target="_blank" rel="noopener">{season.link.label}</a></p>
  </section>;
}

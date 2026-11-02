import {seasonYear} from '../season.ts';
import {ruleProfile, type RulesRegion} from '../regs.ts';
import './season.css';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function SeasonStrip({data, species, region, year}: {data: any; species: string; region: RulesRegion; year: number}) {
  const season = seasonYear(data, species, region, year);
  if (!season) return null;
  const name = species === 'reef' ? 'Lingcod & rockfish' : ruleProfile(data, species, region).name;
  return <section class="app-season" aria-label={`${name} season ${year}`}>
    <h4>{name} season · {year}</h4>
    <ol>{season.months.map(m => <li key={m.month} data-state={m.state}><span>{MONTHS[m.month - 1]}</span> <span>{m.label}</span></li>)}</ol>
    <p>From the reviewed rules (revision {season.revision}). Not legal advice; check the official page. <a href={season.link.href} target="_blank" rel="noopener">{season.link.label}</a></p>
  </section>;
}

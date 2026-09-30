// The Conditions view's seven-day graph card (#meteogram-card, a <details>
// kept in index.html so its open state is native). Renders once: the graph
// inside #meteogram is drawn by meteogram.js (via meteogram-ui.js), which
// replaces the loading line, so this component never re-renders its children.
export const METEOGRAM_LEGEND: ReadonlyArray<readonly [className: string, label: string]> = [
  ['lg-wind', 'Wind kt'], ['lg-gust', 'Gust'], ['lg-sea', 'Seas ft'], ['lg-tide', 'Tide ft'],
  ['lg-go', 'Score 7+'], ['lg-caution', '4–6.9'], ['lg-rough', 'Under 4 or hazard'], ['lg-unknown', 'No score'],
  ['lg-differ', 'Models differ'], ['lg-hatch', 'Outlook after 72 h'],
];

export function MeteogramCard() {
  return (
    <>
      <summary>Next 7 days <small>Tap or drag to pick an hour</small></summary>
      <div id="meteogram"><p class="meteogram-loading">Loading forecast graph…</p></div>
      <ul class="meteogram-legend">
        {METEOGRAM_LEGEND.map(([className, label]) => <li key={className}><i class={className}></i>{label}</li>)}
      </ul>
    </>
  );
}

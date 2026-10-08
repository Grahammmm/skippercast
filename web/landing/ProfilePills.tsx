// Landing profile pills (FE-07, design § 7, D12): Boat / Shore / Spear from
// the profile table, none pressed until the visitor picks one or a stored
// profile exists, so the app's first run still asks a visitor who skipped it.
import {Chip} from '../ui/Chip.tsx';
import {PROFILES, PROFILE_TABLE, type Profile} from '../profile.ts';

export function ProfilePills({value, onChange}: {value: Profile | null; onChange: (next: Profile) => void}) {
  return (
    <div role="group" aria-label="How you fish" class="landing-pills">
      {PROFILES.map(id => (
        <Chip key={id} icon={id} on={id === value} data-profile={id} onClick={() => onChange(id)}>{PROFILE_TABLE[id].label}</Chip>
      ))}
    </div>
  );
}

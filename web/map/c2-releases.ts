// The C2 coast view flag (M9): web/map/stage.ts mounts a region's reviewed, rights-cleared release
// manifest (packages/coast/src/coast3d/mvp.ts admitRelease) only while this is on and the region is
// listed at /data/coast-c2/<region id>/release-manifest.json. Enabling either is a separate data PR.
export const C2_ENABLED: boolean = false;
export const C2_RELEASES: Readonly<Record<string, string>> = Object.freeze({});
